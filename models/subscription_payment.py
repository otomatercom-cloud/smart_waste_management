# Part of Otomater. See LICENSE file for full copyright and licensing details.
from odoo import fields, models


class SwmSubscriptionPayment(models.Model):
    _name = "otm.swm.subscription.payment"
    _description = "Subscription Renewal / Payment Record"
    _order = "payment_date desc, id desc"

    member_id = fields.Many2one(
        "otm.swm.association.member", required=True, ondelete="cascade",
        index=True)
    association_id = fields.Many2one(
        related="member_id.association_id", store=True)
    plan_id = fields.Many2one(
        "otm.swm.subscription.plan", ondelete="set null",
        help="The plan active at the time of this renewal. Kept even "
             "if the plan is later archived; if it's deleted outright, "
             "the name/amount snapshot below still shows what was "
             "actually charged.")
    plan_name = fields.Char(
        required=True,
        help="Snapshot of the plan name at the time of payment - "
             "survives the plan being renamed or deleted later, so this "
             "record always shows what the member actually paid for.")
    amount = fields.Monetary(required=True, currency_field="currency_id")
    currency_id = fields.Many2one(
        "res.currency", required=True,
        default=lambda self: self.env.company.currency_id)
    payment_date = fields.Date(
        required=True, default=fields.Date.context_today)
    period_start = fields.Date()
    period_end = fields.Date()
    recorded_by_id = fields.Many2one(
        "res.users", string="Recorded By", default=lambda self: self.env.user)
    notes = fields.Char()
