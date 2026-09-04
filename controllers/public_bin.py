# Part of Otomater. See LICENSE file for full copyright and licensing details.
import logging
import time

from odoo import http
from odoo.http import request

from ..models.complaint import COMPLAINT_TYPES

_logger = logging.getLogger(__name__)

# Simple in-process rate limiting for public complaint submissions:
# max N submissions per IP per window. Sufficient anti-spam for a single
# worker deployment; put a reverse-proxy limit in front for larger setups.
_RATE_BUCKET = {}
_RATE_MAX = 5
_RATE_WINDOW = 3600


def _rate_limited(ip):
    now = time.time()
    hits = [t for t in _RATE_BUCKET.get(ip, []) if now - t < _RATE_WINDOW]
    if len(hits) >= _RATE_MAX:
        _RATE_BUCKET[ip] = hits
        return True
    hits.append(now)
    _RATE_BUCKET[ip] = hits
    return False


class SwmPublicBin(http.Controller):

    @http.route("/waste/bin/<string:bin_code>", type="http", auth="public",
                website=False, sitemap=False)
    def public_bin(self, bin_code, submitted=None, **kw):
        env = request.env(su=True)
        bin_rec = env["otm.swm.bin"].search(
            [("code", "=", bin_code), ("active", "=", True)], limit=1)
        if not bin_rec:
            return request.not_found()
        Settings = env["res.config.settings"]
        return request.render(
            "smart_waste_management.public_bin_page", {
                "bin": bin_rec,
                "show_fill": Settings.swm_get_bool(
                    "public_show_fill_percent", True),
                "complaints_enabled": Settings.swm_get_bool(
                    "public_complaints_enabled", True),
                "complaint_types": COMPLAINT_TYPES,
                "submitted": bool(submitted),
            })

    @http.route("/waste/bin/<string:bin_code>/details", type="http",
                auth="public", website=False, sitemap=False)
    def public_bin_details(self, bin_code, **kw):
        env = request.env(su=True)
        bin_rec = env["otm.swm.bin"].search(
            [("code", "=", bin_code), ("active", "=", True)], limit=1)
        if not bin_rec:
            return request.not_found()
        History = env["otm.swm.collection.history"]
        cycles = History.search_count([("bin_id", "=", bin_rec.id)])
        breaches = History.search_count(
            [("bin_id", "=", bin_rec.id), ("sla_status", "=", "delayed")])
        last_collected = History.search(
            [("bin_id", "=", bin_rec.id)],
            order="completed_time desc", limit=1)
        Settings = env["res.config.settings"]
        stale_minutes = Settings.swm_get_int("device_offline_minutes", 120)
        return request.render(
            "smart_waste_management.public_bin_details_page", {
                "bin": bin_rec,
                "cycles": cycles,
                "breaches": breaches,
                "on_time": cycles - breaches,
                "last_collected": last_collected,
                "stale_minutes": stale_minutes,
                "show_fill": Settings.swm_get_bool(
                    "public_show_fill_percent", True),
            })

    @http.route("/waste/bin/<string:bin_code>/complaint", type="http",
                auth="public", methods=["POST"], website=False, csrf=True,
                sitemap=False)
    def public_complaint(self, bin_code, **post):
        env = request.env(su=True)
        Settings = env["res.config.settings"]
        if not Settings.swm_get_bool("public_complaints_enabled", True):
            return request.not_found()
        bin_rec = env["otm.swm.bin"].search(
            [("code", "=", bin_code), ("active", "=", True)], limit=1)
        if not bin_rec:
            return request.not_found()
        ip = request.httprequest.remote_addr or "?"
        if _rate_limited(ip):
            _logger.info("SWM public complaint rate-limited from %s", ip)
            return request.redirect(f"/waste/bin/{bin_code}?submitted=1")
        # Honeypot field: bots filling 'website' are silently dropped.
        if (post.get("website") or "").strip():
            return request.redirect(f"/waste/bin/{bin_code}?submitted=1")
        ctype = post.get("complaint_type")
        if ctype not in dict(COMPLAINT_TYPES):
            ctype = "other"
        env["otm.swm.complaint"].create({
            "bin_id": bin_rec.id,
            "complaint_type": ctype,
            "description": (post.get("description") or "")[:2000],
            "reported_by_name": (post.get("reported_by") or "")[:100],
            "is_public": True,
            "reporter_ip": ip,
        })
        return request.redirect(f"/waste/bin/{bin_code}?submitted=1")
