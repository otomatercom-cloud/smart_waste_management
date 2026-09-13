# Part of Otomater. See LICENSE file for full copyright and licensing details.
from odoo import fields, models

DENY_REASONS = [
    ("card_unknown", "Card Not Registered"),
    ("card_inactive", "Card Deactivated"),
    ("subscription_expired", "Subscription Expired/Inactive"),
    ("bin_full_staff_only", "Bin Full - Staff/Supervisor Only"),
    ("balance_low", "Wallet Balance Too Low"),
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
        help="Bin weight reported at the moment of the tap itself - a "
             "single instant reading, before anything more may have "
             "been added. See Weight Deposited for the running total "
             "over the whole open session.")
    session_start_weight_kg = fields.Float(
        digits=(6, 2), readonly=True,
        help="Bin weight at the moment this visit's lock opened.")
    session_end_weight_kg = fields.Float(
        digits=(6, 2), readonly=True,
        help="Latest bin weight reported before the open-session "
             "window closed (someone may have added several bags "
             "during this window - each reading updates this).")
    session_closed = fields.Boolean(
        default=False, readonly=True,
        help="On once the open-session window has ended and "
             "weight_deposited_kg has been finalised.")
    weight_deposited_kg = fields.Float(
        string="Weight Deposited (kg)", digits=(6, 2), readonly=True,
        help="What this person actually put in during their visit: "
             "session_end_weight_kg minus session_start_weight_kg, "
             "finalised once the open-session window closes. This is "
             "the number to use for \"how much did they dump\", not "
             "the single-instant weight_kg above.")
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id)
    billing_rate_per_kg = fields.Monetary(
        currency_field="currency_id", readonly=True,
        help="The member's plan rate at the moment this visit opened - "
             "snapshotted so a later price change never rewrites what "
             "this visit actually cost. 0 for staff cards, flat plans, "
             "or when wallet billing was off at the time.")
    amount_charged = fields.Monetary(
        currency_field="currency_id", readonly=True,
        help="weight_deposited_kg x billing_rate_per_kg, deducted from "
             "the member's wallet when the visit's session closed.")
    wallet_balance_after = fields.Monetary(
        currency_field="currency_id", readonly=True,
        help="The member's wallet balance immediately after this "
             "visit's charge was deducted.")
