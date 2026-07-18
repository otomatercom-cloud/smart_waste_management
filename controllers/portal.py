# Part of Otomater. See LICENSE file for full copyright and licensing details.
from odoo import http
from odoo.http import request

OPEN_STATES = ("new", "assigned", "accepted", "in_progress")


class SwmPortal(http.Controller):

    # ------------------------------------------------------------------
    # Association member dashboard
    # ------------------------------------------------------------------
    @http.route(["/my/waste", "/my/waste/page/<int:page>"], type="http",
                auth="user", website=False)
    def member_dashboard(self, page=1, street_id=None, status=None, **kw):
        env = request.env
        user = env.user
        member = env["otm.swm.association.member"]._member_for_user(user)
        staff = env["otm.swm.staff"]._staff_for_user(user)
        if not member and staff:
            return request.redirect("/my/waste/staff")

        # Record rules already limit visibility; the explicit domain keeps
        # the page meaningful for members of exactly one association.
        Bin = env["otm.swm.bin"]
        domain = [("active", "=", True)]
        if member:
            domain.append(("association_id", "=", member.association_id.id))
        if street_id:
            try:
                domain.append(("street_id", "=", int(street_id)))
            except ValueError:
                street_id = None
        if status:
            domain.append(("status", "=", status))
        bins = Bin.search(domain, order="status desc, code")
        all_bins = Bin.search(
            [("active", "=", True)]
            + ([("association_id", "=", member.association_id.id)]
               if member else []))
        kpi = {
            "total": len(all_bins),
            "available": len(all_bins.filtered(
                lambda b: b.status in ("available", "collected"))),
            "nearly_full": len(all_bins.filtered(
                lambda b: b.status == "nearly_full")),
            "full": len(all_bins.filtered(lambda b: b.status == "full")),
            "pending": len(all_bins.filtered(
                lambda b: b.status in ("collection_pending",
                                       "collection_in_progress"))),
            "offline": len(all_bins.filtered(
                lambda b: b.status == "offline")),
            "delayed": env["otm.swm.collection.request"].search_count([
                ("state", "in", OPEN_STATES),
                ("escalation_level", ">", 0),
            ] + ([("association_id", "=", member.association_id.id)]
                 if member else [])),
        }
        streets = env["otm.swm.street"].search(
            [("association_id", "=", member.association_id.id)]
            if member else [])
        return request.render("smart_waste_management.portal_member_dashboard", {
            "member": member,
            "bins": bins,
            "kpi": kpi,
            "streets": streets,
            "selected_street": int(street_id) if street_id else None,
            "selected_status": status or "",
            "page_name": "swm_dashboard",
        })

    # ------------------------------------------------------------------
    # Telegram connect / disconnect
    # ------------------------------------------------------------------
    @http.route("/my/waste/telegram", type="http", auth="user", website=False)
    def telegram_connect(self, **kw):
        env = request.env
        member = env["otm.swm.association.member"]._member_for_user(env.user)
        if not member:
            return request.redirect("/my/waste")
        token = None
        deep_link = ""
        if not member.telegram_connected:
            token = env["otm.swm.telegram.token"].issue_for_member(member)
            deep_link = token.deep_link()
        return request.render("smart_waste_management.portal_telegram_connect", {
            "member": member,
            "deep_link": deep_link,
            "page_name": "swm_telegram",
        })

    @http.route("/my/waste/telegram/disconnect", type="http", auth="user",
                methods=["POST"], website=False, csrf=True)
    def telegram_disconnect(self, **kw):
        env = request.env
        member = env["otm.swm.association.member"]._member_for_user(env.user)
        if member:
            member.action_disconnect_telegram()
        return request.redirect("/my/waste/telegram")

    @http.route("/my/waste/preferences", type="http", auth="user",
                methods=["POST"], website=False, csrf=True)
    def save_preferences(self, **post):
        env = request.env
        member = env["otm.swm.association.member"]._member_for_user(env.user)
        if member:
            member.sudo().write({
                "notify_bin_full": bool(post.get("notify_bin_full")),
                "notify_delayed": bool(post.get("notify_delayed")),
                "notify_collected": bool(post.get("notify_collected")),
                "notify_available": bool(post.get("notify_available")),
            })
        return request.redirect("/my/waste/telegram")

    # ------------------------------------------------------------------
    # Collection staff dashboard
    # ------------------------------------------------------------------
    @http.route("/my/waste/staff", type="http", auth="user", website=False)
    def staff_dashboard(self, **kw):
        env = request.env
        staff = env["otm.swm.staff"]._staff_for_user(env.user)
        if not staff:
            return request.redirect("/my/waste")
        requests_ = env["otm.swm.collection.request"].sudo().search([
            ("staff_id", "=", staff.id),
            ("state", "in", OPEN_STATES),
        ], order="full_detected_time")
        return request.render("smart_waste_management.portal_staff_dashboard", {
            "staff": staff,
            "requests": requests_,
            "page_name": "swm_staff",
        })

    @http.route("/my/waste/staff/request/<int:request_id>/<string:action>",
                type="http", auth="user", methods=["POST"], website=False,
                csrf=True)
    def staff_request_action(self, request_id, action, **kw):
        env = request.env
        staff = env["otm.swm.staff"]._staff_for_user(env.user)
        rec = env["otm.swm.collection.request"].sudo().browse(request_id)
        if staff and rec.exists() and rec.staff_id == staff:
            if action == "accept" and rec.state in ("new", "assigned"):
                rec.action_accept()
            elif action == "start" and rec.state in ("assigned", "accepted"):
                rec.action_start()
        return request.redirect("/my/waste/staff")
