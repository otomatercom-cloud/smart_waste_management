# Part of Otomater. See LICENSE file for full copyright and licensing details.
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

STAFF_GROUPS = (
    "smart_waste_management.group_swm_collection_staff",
    "smart_waste_management.group_swm_supervisor",
)


class SwmStaffQrController(http.Controller):
    """Login-protected page opened by scanning the staff QR inside the
    bin lid. Staff approve the bin as emptied; the model method only
    accepts when the sensor corroborates."""

    def _check_staff(self):
        user = request.env.user
        return any(user.has_group(g) for g in STAFF_GROUPS)

    def _get_bin(self, bin_code):
        # sudo lookup: staff record rules scope bins by assignment, but
        # any collection staff physically at the bin may confirm it.
        return request.env["otm.swm.bin"].sudo().search(
            [("code", "=", bin_code), ("active", "=", True)], limit=1)

    @http.route(["/waste/bin/<string:bin_code>/collect"],
                type="http", auth="user", website=False, sitemap=False)
    def staff_collect_page(self, bin_code, **kwargs):
        if not self._check_staff():
            return request.render(
                "smart_waste_management.staff_collect_denied", {})
        bin_rec = self._get_bin(bin_code)
        if not bin_rec:
            return request.not_found()
        result_reason = kwargs.get("r") or ""
        result_ok = kwargs.get("ok") == "1"
        messages = {
            "approved": "Collection approved — bin is now Available.",
            "not_empty": "Sensor does not read empty yet. Empty the bin, "
                         "close the lid, wait for the next sensor reading "
                         "and try again.",
            "stale": "No recent sensor reading. Close the lid, wait a "
                     "moment for the sensor to report, then try again.",
            "maintenance": "Bin is under maintenance — approval disabled.",
        }
        return request.render(
            "smart_waste_management.staff_collect_page", {
                "bin": bin_rec,
                "result_reason": result_reason,
                "result_ok": result_ok,
                "result_message": messages.get(result_reason, ""),
            })

    @http.route(["/waste/bin/<string:bin_code>/collect/approve"],
                type="http", auth="user", methods=["POST"], csrf=True,
                website=False, sitemap=False)
    def staff_collect_approve(self, bin_code, **kwargs):
        if not self._check_staff():
            return request.render(
                "smart_waste_management.staff_collect_denied", {})
        bin_rec = self._get_bin(bin_code)
        if not bin_rec:
            return request.not_found()
        # Keep the real user identity for the audit trail, with sudo so
        # any staff physically at the bin can confirm regardless of
        # assignment-scope record rules.
        result = bin_rec.with_user(request.env.user).sudo()\
            .qr_confirm_collection()
        _logger.info(
            "SWM staff QR approve: bin=%s user=%s ok=%s reason=%s",
            bin_code, request.env.user.login,
            result.get("ok"), result.get("reason"))
        return request.redirect(
            f"/waste/bin/{bin_code}/collect?ok="
            f"{'1' if result.get('ok') else '0'}&r={result.get('reason')}")
