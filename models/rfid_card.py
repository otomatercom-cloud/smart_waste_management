# Part of Otomater. See LICENSE file for full copyright and licensing details.
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

HOLDER_TYPES = [
    ("member", "Association Member"),
    ("staff", "Collection Staff / Supervisor"),
]


class SwmRfidCard(models.Model):
    _name = "otm.swm.rfid.card"
    _description = "Smart Bin RFID Access Card"
    _rec_name = "card_uid"
    _order = "create_date desc"

    card_uid = fields.Char(
        string="Card UID", required=True, copy=False, index=True,
        help="The unique ID read off the RFID tag by the ESP32 reader "
             "(e.g. the 4/7-byte UID an RC522/PN532 module reports).")
    holder_type = fields.Selection(
        HOLDER_TYPES, required=True, default="member",
        help="A member card is checked against their subscription and "
             "denied while a bin is full - only staff/supervisor cards "
             "open a full bin, so a collector can service and empty it.")
    member_id = fields.Many2one(
        "otm.swm.association.member", string="Member",
        ondelete="cascade")
    staff_id = fields.Many2one(
        "otm.swm.staff", string="Staff / Supervisor",
        ondelete="cascade")
    holder_name = fields.Char(
        compute="_compute_holder_name", store=True, string="Issued To")
    association_id = fields.Many2one(
        related="member_id.association_id", store=True, readonly=True)
    active = fields.Boolean(default=True)
    issued_date = fields.Date(default=fields.Date.context_today)
    notes = fields.Char()
    access_count = fields.Integer(
        compute="_compute_access_count", string="Total Taps")

    _sql_constraints = [
        ("card_uid_unique", "unique(card_uid)",
         "This RFID card UID is already registered."),
    ]

    @api.constrains("holder_type", "member_id", "staff_id")
    def _check_exactly_one_holder(self):
        for rec in self:
            if rec.holder_type == "member" and not rec.member_id:
                raise ValidationError(
                    _("A member card needs a Member selected."))
            if rec.holder_type == "staff" and not rec.staff_id:
                raise ValidationError(
                    _("A staff card needs a Staff / Supervisor selected."))
            if rec.member_id and rec.staff_id:
                raise ValidationError(
                    _("A card can be issued to a member OR to staff, "
                      "not both."))

    @api.onchange("holder_type")
    def _onchange_holder_type(self):
        # Clear whichever side no longer applies so the constraint above
        # never sees both set from a leftover value in the other field.
        if self.holder_type == "member":
            self.staff_id = False
        elif self.holder_type == "staff":
            self.member_id = False

    @api.depends("member_id.name", "staff_id.name")
    def _compute_holder_name(self):
        for rec in self:
            rec.holder_name = rec.member_id.name or rec.staff_id.name or ""

    def _compute_access_count(self):
        Log = self.env["otm.swm.bin.access.log"]
        for rec in self:
            rec.access_count = Log.search_count(
                [("card_id", "=", rec.id)]) if rec.id else 0

    def action_view_access_log(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"Access Log — {self.card_uid}",
            "res_model": "otm.swm.bin.access.log",
            "view_mode": "list,form",
            "domain": [("card_id", "=", self.id)],
        }
