# Part of Otomater. See LICENSE file for full copyright and licensing details.
from odoo import api, fields, models


class SwmStaff(models.Model):
    _name = "otm.swm.staff"
    _description = "Waste Collection Staff"
    _order = "name"

    name = fields.Char(string="Staff Name", required=True)
    user_id = fields.Many2one(
        "res.users", string="Employee / User",
        help="Odoo login used by this staff member; drives the staff "
             "portal dashboard and record rules.")
    phone = fields.Char()
    telegram_chat_id = fields.Char(
        string="Telegram Chat ID",
        groups="smart_waste_management.group_swm_manager")
    telegram_username = fields.Char(string="Telegram Account")
    telegram_deep_link = fields.Char(
        string="Telegram Connect Link", compute="_compute_telegram_deep_link",
        help="Personal link into the shared Otomater Telegram bot for "
             "this staff's linked user. Send it to them, or generate a "
             "QR from it, so they can self-connect instead of an admin "
             "typing their chat ID by hand.")
    is_supervisor = fields.Boolean(string="Collection Supervisor")
    supervisor_id = fields.Many2one(
        "otm.swm.staff", string="Supervisor",
        domain=[("is_supervisor", "=", True)])
    active = fields.Boolean(default=True)
    rfid_card_ids = fields.One2many(
        "otm.swm.rfid.card", "staff_id", string="RFID Cards",
        help="Cards issued to this staff/supervisor always open a bin, "
             "including while it's full - unlike a member card, which "
             "is denied on a full bin so a collector can service it.")
    rfid_card_count = fields.Integer(compute="_compute_rfid_card_count")

    def _compute_rfid_card_count(self):
        for rec in self:
            rec.rfid_card_count = len(rec.rfid_card_ids)

    def action_view_rfid_cards(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"RFID Cards — {self.name}",
            "res_model": "otm.swm.rfid.card",
            "view_mode": "list,form",
            "domain": [("staff_id", "=", self.id)],
            "context": {"default_staff_id": self.id,
                        "default_holder_type": "staff"},
        }

    corporation_ids = fields.Many2many(
        "otm.swm.corporation", string="Assigned Corporations")
    ward_ids = fields.Many2many("otm.swm.ward", string="Assigned Wards")
    association_ids = fields.Many2many(
        "otm.swm.association", string="Assigned Associations")
    street_ids = fields.Many2many("otm.swm.street", string="Assigned Streets")
    bin_ids = fields.Many2many("otm.swm.bin", string="Assigned Bins")

    open_request_count = fields.Integer(compute="_compute_open_requests")

    def _compute_open_requests(self):
        Request = self.env["otm.swm.collection.request"]
        for rec in self:
            rec.open_request_count = Request.search_count([
                ("staff_id", "=", rec.id),
                ("state", "in", ("new", "assigned", "accepted",
                                 "in_progress")),
            ])

    @api.model
    def _staff_for_user(self, user):
        return self.sudo().search([("user_id", "=", user.id)], limit=1)

    def _compute_telegram_deep_link(self):
        for rec in self:
            rec.telegram_deep_link = (
                rec.sudo().user_id.telegram_deep_link
                if rec.user_id else False)

    def action_sync_telegram_from_bot(self):
        """Pull the linked chat_id from the shared software_telegram bot
        (via this staff's user) into this record's own fields — see
        the identical method on otm.swm.association.member for why."""
        for rec in self:
            user = rec.sudo().user_id
            contact = user.sudo().telegram_contact_id if user else False
            if not contact:
                continue
            rec.sudo().write({
                "telegram_chat_id": contact.chat_id,
                "telegram_username": contact.telegram_username or "",
            })
        return True

    def action_view_open_requests(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Open Collection Requests",
            "res_model": "otm.swm.collection.request",
            "view_mode": "list,form",
            "domain": [("staff_id", "=", self.id),
                       ("state", "in", ("new", "assigned", "accepted",
                                        "in_progress"))],
        }
