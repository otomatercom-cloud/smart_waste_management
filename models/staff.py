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
    is_supervisor = fields.Boolean(string="Collection Supervisor")
    supervisor_id = fields.Many2one(
        "otm.swm.staff", string="Supervisor",
        domain=[("is_supervisor", "=", True)])
    active = fields.Boolean(default=True)

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
