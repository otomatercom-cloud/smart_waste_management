# Part of Otomater. See LICENSE file for full copyright and licensing details.
from odoo import fields, models

DENY_REASONS = [
    ("card_unknown", "Card Not Registered"),
    ("card_inactive", "Card Deactivated"),
    ("subscription_expired", "Subscription Expired/Inactive"),
]


class SwmBinAccessLog(models.Model):
    _name = "otm.swm.bin.access.log"
    _description = "Smart Bin RFID Access Log"
    _order = "create_date desc"

    bin_id = fields.Many2one(
        "otm.swm.bin", required=True, ondelete="cascade", index=True)
    bin_code = fields.Char(related="bin_id.code", store=True)
    street_id = fields.Many2one(related="bin_id.street_id", store=True)
    association_id = fields.Many2one(
        related="bin_id.association_id", store=True)
    card_uid = fields.Char(required=True, index=True)
    card_id = fields.Many2one("otm.swm.rfid.card", ondelete="set null")
    member_id = fields.Many2one(
        "otm.swm.association.member", ondelete="set null",
        help="Who tapped the card - resolved from the card at the time "
             "of the tap. This is the answer to \"who put waste in the "
             "bin\": every open is tied to the person whose card opened "
             "it.")
    granted = fields.Boolean(index=True)
    deny_reason = fields.Selection(DENY_REASONS)
    weight_kg = fields.Float(
        string="Weight (kg)", digits=(6, 2),
        help="Bin weight reported by the load cell at the time of this "
             "tap, if the device sent one and weight capture is enabled.")
