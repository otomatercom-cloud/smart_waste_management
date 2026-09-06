# Part of Otomater. See LICENSE file for full copyright and licensing details.
from odoo import api, fields, models


class SwmRfidCard(models.Model):
    _name = "otm.swm.rfid.card"
    _description = "Smart Bin RFID Access Card"
    _rec_name = "card_uid"
    _order = "create_date desc"

    card_uid = fields.Char(
        string="Card UID", required=True, copy=False, index=True,
        help="The unique ID read off the RFID tag by the ESP32 reader "
             "(e.g. the 4/7-byte UID an RC522/PN532 module reports).")
    member_id = fields.Many2one(
        "otm.swm.association.member", string="Issued To", required=True,
        ondelete="cascade")
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
