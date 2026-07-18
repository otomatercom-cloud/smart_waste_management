# Part of Otomater. See LICENSE file for full copyright and licensing details.
from odoo import api, fields, models


class SwmAssociation(models.Model):
    _name = "otm.swm.association"
    _description = "Residential Association"
    _inherit = ["mail.thread"]
    _order = "name"

    name = fields.Char(string="Association Name", required=True, tracking=True)
    code = fields.Char(string="Association Code", required=True, copy=False)
    corporation_id = fields.Many2one(
        "otm.swm.corporation", required=True,
        string="Corporation / Municipality")
    zone_id = fields.Many2one(
        "otm.swm.zone", string="Zone",
        domain="[('corporation_id', '=', corporation_id)]")
    ward_id = fields.Many2one(
        "otm.swm.ward", string="Ward",
        domain="[('zone_id', '=', zone_id)]")
    address = fields.Text()
    president_id = fields.Many2one("res.partner", string="President")
    secretary_id = fields.Many2one("res.partner", string="Secretary")
    manager_user_id = fields.Many2one(
        "res.users", string="Association Manager", tracking=True)
    phone = fields.Char(string="Contact Number")
    email = fields.Char()
    telegram_group_chat_id = fields.Char(
        string="Telegram Group Chat ID", groups="smart_waste_management.group_swm_manager")
    active = fields.Boolean(default=True)

    member_ids = fields.One2many(
        "otm.swm.association.member", "association_id", string="Members")
    street_ids = fields.One2many(
        "otm.swm.street", "association_id", string="Streets")
    bin_ids = fields.One2many("otm.swm.bin", "association_id", string="Bins")

    member_count = fields.Integer(compute="_compute_counts", string="Members #")
    street_count = fields.Integer(compute="_compute_counts", string="Streets #")
    bin_count = fields.Integer(
        compute="_compute_bin_counts", store=True, string="Bins #")
    full_bin_count = fields.Integer(
        compute="_compute_bin_counts", store=True, string="Full Bins")

    _sql_constraints = [
        ("code_uniq", "unique(code)", "Association code must be unique."),
    ]

    def _compute_counts(self):
        for rec in self:
            rec.member_count = len(rec.member_ids)
            rec.street_count = len(rec.street_ids)

    @api.depends("bin_ids", "bin_ids.status", "bin_ids.active")
    def _compute_bin_counts(self):
        for rec in self:
            bins = rec.bin_ids.filtered("active")
            rec.bin_count = len(bins)
            rec.full_bin_count = len(bins.filtered(
                lambda b: b.status == "full"))

    def action_view_streets(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Streets",
            "res_model": "otm.swm.street",
            "view_mode": "list,form",
            "domain": [("association_id", "=", self.id)],
            "context": {"default_association_id": self.id,
                        "default_corporation_id": self.corporation_id.id},
        }

    def action_view_bins(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Smart Bins",
            "res_model": "otm.swm.bin",
            "view_mode": "kanban,list,form",
            "domain": [("association_id", "=", self.id)],
            "context": {"default_association_id": self.id},
        }


class SwmAssociationMember(models.Model):
    _name = "otm.swm.association.member"
    _description = "Association Member"
    _order = "association_id, name"

    name = fields.Char(string="Member Name", required=True)
    association_id = fields.Many2one(
        "otm.swm.association", required=True, ondelete="cascade",
        string="Association")
    corporation_id = fields.Many2one(
        related="association_id.corporation_id", store=True, readonly=True)
    street_id = fields.Many2one(
        "otm.swm.street", string="Street",
        domain="[('association_id', '=', association_id)]")
    house_no = fields.Char(string="House Name / Number")
    phone = fields.Char()
    email = fields.Char()
    partner_id = fields.Many2one("res.partner", string="Contact")
    user_id = fields.Many2one(
        "res.users", string="Portal User",
        help="Portal login of this member; drives portal record rules.")
    active = fields.Boolean(default=True)

    # Telegram linkage — chat identifiers restricted to managers.
    telegram_connected = fields.Boolean(
        string="Telegram Connected", readonly=True, copy=False)
    telegram_chat_id = fields.Char(
        readonly=True, copy=False,
        groups="smart_waste_management.group_swm_manager")
    telegram_user_id = fields.Char(
        readonly=True, copy=False,
        groups="smart_waste_management.group_swm_manager")
    telegram_username = fields.Char(readonly=True, copy=False)
    telegram_connected_on = fields.Datetime(readonly=True, copy=False)

    # Notification preferences
    notify_bin_full = fields.Boolean(
        string="Notify: My Street Bin Is Full", default=True)
    notify_delayed = fields.Boolean(
        string="Notify: Collection Delayed", default=True)
    notify_collected = fields.Boolean(
        string="Notify: Waste Collected", default=True)
    notify_available = fields.Boolean(
        string="Notify: Bin Available Again", default=False)

    def action_disconnect_telegram(self):
        self.sudo().write({
            "telegram_connected": False,
            "telegram_chat_id": False,
            "telegram_user_id": False,
            "telegram_username": False,
            "telegram_connected_on": False,
        })
        return True

    @api.model
    def _member_for_user(self, user):
        return self.sudo().search([("user_id", "=", user.id)], limit=1)
