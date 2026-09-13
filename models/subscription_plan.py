# Part of Otomater. See LICENSE file for full copyright and licensing details.
from odoo import fields, models


class SwmSubscriptionPlan(models.Model):
    _name = "otm.swm.subscription.plan"
    _description = "RFID Bin Access Subscription Plan"
    _order = "duration_days"

    name = fields.Char(
        required=True,
        help='E.g. "Monthly Household", "Quarterly", "Annual Commercial".')
    price = fields.Monetary(
        required=True, currency_field="currency_id",
        help="Amount charged for one renewal on this plan. Change this "
             "any time - past renewals keep the price that applied when "
             "they were made, so editing this never rewrites history.")
    currency_id = fields.Many2one(
        "res.currency", required=True,
        default=lambda self: self.env.company.currency_id)
    duration_days = fields.Integer(
        required=True, default=30,
        help="How many days one renewal on this plan covers. 30 for "
             "monthly, 90 for quarterly, 365 for annual, or any custom "
             "length.")
    rate_per_kg = fields.Monetary(
        currency_field="currency_id", default=0.0,
        help="What one kg deposited costs, deducted directly from the "
             "member's wallet balance at that visit's close. Set "
             "whatever rate you charge - e.g. 30 for Rs 30/kg. Leave "
             "at 0 for a flat plan with no per-kg billing at all "
             "(wallet balance is never touched).")
    active = fields.Boolean(default=True)
    description = fields.Char()
    member_count = fields.Integer(compute="_compute_member_count")

    def _compute_member_count(self):
        Member = self.env["otm.swm.association.member"]
        for rec in self:
            rec.member_count = (
                Member.search_count([("subscription_plan_id", "=", rec.id)])
                if rec.id else 0)

    def _compute_member_count(self):
        Member = self.env["otm.swm.association.member"]
        for rec in self:
            rec.member_count = (
                Member.search_count([("subscription_plan_id", "=", rec.id)])
                if rec.id else 0)

    def action_view_members(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"Members on {self.name}",
            "res_model": "otm.swm.association.member",
            "view_mode": "list,form",
            "domain": [("subscription_plan_id", "=", self.id)],
        }
