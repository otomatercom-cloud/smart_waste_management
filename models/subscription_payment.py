# Part of Otomater. See LICENSE file for full copyright and licensing details.
from odoo import api, fields, models


class SwmSubscriptionPayment(models.Model):
    _name = "otm.swm.subscription.payment"
    _description = "Subscription Renewal / Payment Record"
    _order = "payment_date desc, id desc"
    _rec_name = "display_name"

    display_name = fields.Char(compute="_compute_display_name", store=True)

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
    plan_price_at_payment = fields.Monetary(
        currency_field="currency_id", readonly=True,
        help="Snapshot of the plan's price at the moment this record "
             "was created - the reference amount is compared against, "
             "independent of later price changes on the plan itself.")
    is_underpaid = fields.Boolean(
        compute="_compute_is_underpaid", store=True,
        help="Amount is less than the plan's price at the time of "
             "payment. A Telegram notice is sent to the member once, "
             "when this first becomes true, if enabled in Settings.")
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

    @api.depends("member_id.name", "plan_name", "payment_date", "amount")
    def _compute_display_name(self):
        for rec in self:
            date_str = rec.payment_date.strftime("%d %b %Y") \
                if rec.payment_date else ""
            rec.display_name = (
                f"{rec.member_id.name or 'Unknown'} — "
                f"{rec.plan_name or 'No Plan'} ({date_str})")

    @api.depends("amount", "plan_price_at_payment")
    def _compute_is_underpaid(self):
        for rec in self:
            rec.is_underpaid = bool(
                rec.plan_price_at_payment
                and rec.amount < rec.plan_price_at_payment)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if "plan_price_at_payment" not in vals and vals.get("plan_id"):
                plan = self.env["otm.swm.subscription.plan"].browse(
                    vals["plan_id"])
                vals["plan_price_at_payment"] = plan.price
        records = super().create(vals_list)
        records._notify_if_underpaid()
        return records

    def _notify_if_underpaid(self):
        """Telegram the member once when a recorded payment is less
        than the plan's price at the time - e.g. a partial or
        discounted payment a staff member entered by hand. Renewals
        made through the normal Renew Subscription button always
        charge the full plan price, so this only fires for payments
        someone has deliberately entered at a lower amount."""
        Settings = self.env["res.config.settings"]
        if not Settings.swm_get_bool("underpayment_alerts_enabled", True):
            return
        Bridge = self.env["software.telegram.message"].sudo()
        for rec in self.filtered(
                lambda r: r.is_underpaid and r.member_id.telegram_connected):
            shortfall = rec.plan_price_at_payment - rec.amount
            text = (
                f"⚠️ We recorded a payment of {rec.currency_id.symbol}"
                f"{rec.amount:.2f} for your {rec.plan_name} subscription, "
                f"which is {rec.currency_id.symbol}{shortfall:.2f} short "
                f"of the full {rec.currency_id.symbol}"
                f"{rec.plan_price_at_payment:.2f} price. Please contact "
                f"your association to settle the balance.")
            Bridge.send_direct(
                chat_id=rec.member_id.telegram_chat_id, text=text,
                event_type="swm_subscription_underpaid",
                res_model=self._name, res_id=rec.id)
