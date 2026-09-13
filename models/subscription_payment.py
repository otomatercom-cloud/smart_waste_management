# Part of Otomater. See LICENSE file for full copyright and licensing details.
from odoo import _, api, fields, models

STATES = [
    ("pending", "Pending Approval"),
    ("approved", "Approved"),
    ("rejected", "Rejected"),
]


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

    state = fields.Selection(
        STATES, default="approved", required=True,
        help="A payment a manager records directly (e.g. via Renew "
             "Subscription, or entered by hand under Subscription "
             "Payments) is approved immediately - it already happened "
             "under their own authority. A member's own self-service "
             "\"I've Paid\" request from the portal starts Pending: "
             "the wallet top-up and expiry extension only take effect "
             "once a manager reviews and approves it.")
    approved_by_id = fields.Many2one(
        "res.users", readonly=True, string="Approved/Rejected By")
    approved_date = fields.Datetime(readonly=True)
    is_self_service = fields.Boolean(
        default=False, readonly=True,
        help="True when the member submitted this themselves from the "
             "portal, rather than a manager recording it directly.")

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
        # Auto-approved (the default, e.g. Renew Subscription or a
        # manager typing one in by hand) takes effect immediately.
        # Pending (a member's own portal request) waits for
        # action_approve() and touches nothing until then.
        records.filtered(lambda r: r.state == "approved")._apply_to_member()
        records._notify_if_underpaid()
        records.filtered(
            lambda r: r.state == "pending")._notify_manager_pending()
        return records

    def _apply_to_member(self):
        """The one place that actually extends a subscription: tops up
        the wallet by this payment's amount, extends expiry by the
        plan's duration (from today, not from the old expiry - a
        lapsed member gets a fresh full period rather than back-dated
        coverage), and activates the subscription. Called immediately
        for an approved payment, or later from action_approve() for a
        payment that started Pending."""
        for rec in self:
            member = rec.member_id
            days = (rec.plan_id.duration_days if rec.plan_id else
                    self.env["res.config.settings"].swm_get_int(
                        "subscription_renewal_days", 30))
            today = fields.Date.context_today(rec)
            new_expiry = fields.Date.add(today, days=days)
            member.write({
                "subscription_active": True,
                "subscription_expiry": new_expiry,
                "subscription_last_reminder_date": False,
                "wallet_balance": member.wallet_balance + rec.amount,
            })
            vals = {}
            if not rec.period_start:
                vals["period_start"] = today
            if not rec.period_end:
                vals["period_end"] = new_expiry
            if vals:
                rec.write(vals)

    def action_approve(self):
        """Manager approves a member's pending self-service payment
        request: applies the wallet top-up and expiry extension now,
        and tells the member via Telegram."""
        for rec in self.filtered(lambda r: r.state == "pending"):
            rec.write({
                "state": "approved",
                "approved_by_id": self.env.user.id,
                "approved_date": fields.Datetime.now(),
            })
            rec._apply_to_member()
            rec._notify_member_decision(approved=True)
        return True

    def action_reject(self):
        """Manager rejects a pending request - nothing about the
        member's wallet or expiry is touched, it simply never took
        effect. Use Notes to record why before rejecting."""
        for rec in self.filtered(lambda r: r.state == "pending"):
            rec.write({
                "state": "rejected",
                "approved_by_id": self.env.user.id,
                "approved_date": fields.Datetime.now(),
            })
            rec._notify_member_decision(approved=False)
        return True

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

    def _notify_manager_pending(self):
        """Telegram the association's manager the moment a member
        submits a self-service payment request, so it doesn't sit
        unapproved indefinitely. Best-effort: silently does nothing if
        the association has no manager_user_id or they're not
        Telegram-connected via a staff record."""
        Staff = self.env["otm.swm.staff"].sudo()
        Bridge = self.env["software.telegram.message"].sudo()
        for rec in self:
            manager_user = rec.member_id.association_id.manager_user_id
            if not manager_user:
                continue
            staff = Staff.search(
                [("user_id", "=", manager_user.id)], limit=1)
            if not staff or not staff.telegram_chat_id:
                continue
            text = (
                f"💳 New subscription payment request\n"
                f"Member: {rec.member_id.name}\n"
                f"Plan: {rec.plan_name}\n"
                f"Amount claimed: {rec.currency_id.symbol}{rec.amount:.2f}\n"
                f"Review it under Subscription Payments.")
            Bridge.send_direct(
                chat_id=staff.telegram_chat_id, text=text,
                event_type="swm_subscription_pending",
                res_model=self._name, res_id=rec.id)

    def _notify_member_decision(self, approved):
        member = self.member_id if len(self) == 1 else None
        Bridge = self.env["software.telegram.message"].sudo()
        for rec in self:
            if not rec.member_id.telegram_connected:
                continue
            text = (
                (f"✅ Your payment of {rec.currency_id.symbol}"
                 f"{rec.amount:.2f} for {rec.plan_name} has been "
                 f"approved. Your subscription is now active until "
                 f"{rec.member_id.subscription_expiry}.")
                if approved else
                (f"❌ Your payment claim of {rec.currency_id.symbol}"
                 f"{rec.amount:.2f} for {rec.plan_name} was not "
                 f"approved. Please contact your association."))
            Bridge.send_direct(
                chat_id=rec.member_id.telegram_chat_id, text=text,
                event_type="swm_subscription_decision",
                res_model=self._name, res_id=rec.id)
