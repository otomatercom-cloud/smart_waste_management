# Part of Otomater. See LICENSE file for full copyright and licensing details.
from odoo import fields, models

DENY_REASONS = [
    ("card_unknown", "Card Not Registered"),
    ("card_inactive", "Card Deactivated"),
    ("subscription_expired", "Subscription Expired/Inactive"),
    ("bin_full_staff_only", "Bin Full - Staff/Supervisor Only"),
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
        help="Who tapped the card, if it was a member card - resolved "
             "from the card at the time of the tap. This is the answer "
             "to \"who put waste in the bin\" for residents.")
    staff_id = fields.Many2one(
        "otm.swm.staff", ondelete="set null",
        help="Who tapped the card, if it was a staff/supervisor card - "
             "these can open a bin even while full, to service it.")
    holder_name = fields.Char(
        help="Snapshot of the card holder's name at the time of the "
             "tap - survives the member/staff record or card being "
             "deleted later.")
    granted = fields.Boolean(index=True)
    deny_reason = fields.Selection(DENY_REASONS)
    weight_kg = fields.Float(
        string="Weight (kg)", digits=(6, 2),
        help="Bin weight reported by the load cell at the time of this "
             "tap, if the device sent one and weight capture is enabled.")
