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
    # connected + chat_id are editable so administrators can link a
    # member manually (e.g. before the webhook/SSL is available); the
    # QR self-registration flow fills them automatically as well.
    telegram_connected = fields.Boolean(
        string="Telegram Connected", copy=False,
        help="On when the member can receive Telegram messages. Set "
             "automatically by the QR registration flow, or manually "
             "together with a Chat ID.")
    telegram_chat_id = fields.Char(
        copy=False,
        groups="smart_waste_management.group_swm_manager",
        help="Numeric Telegram chat ID. Ask the member to message "
             "@userinfobot, or read it from the bot's getUpdates.")
    telegram_user_id = fields.Char(
        copy=False,
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

    # ---- RFID / subscription access control ----
    subscription_active = fields.Boolean(
        default=True,
        help="Master switch for this member's bin access. Off means "
             "every RFID card issued to them is denied, regardless of "
             "expiry date.")
    subscription_expiry = fields.Date(
        help="Access is denied once this date has passed, even if "
             "Subscription Active is still on. Leave empty for no "
             "expiry (access controlled by the Active switch alone).")
    subscription_valid = fields.Boolean(
        compute="_compute_subscription_valid", store=True,
        string="Subscription Valid",
        help="True when the member can open bins right now: Active is "
             "on AND (no expiry date, or the expiry date hasn't passed).")
    subscription_last_reminder_date = fields.Date(
        readonly=True, copy=False,
        help="When the last renewal reminder was sent. Used only to "
             "space reminders out - never sent more than once during "
             "the pre-expiry window, and roughly monthly (not daily) "
             "once lapsed.")
    rfid_card_ids = fields.One2many(
        "otm.swm.rfid.card", "member_id", string="RFID Cards")
    rfid_card_count = fields.Integer(
        compute="_compute_rfid_card_count")
    subscription_plan_id = fields.Many2one(
        "otm.swm.subscription.plan", string="Subscription Plan",
        help="Which plan's price and duration Renew Subscription uses. "
             "Leave empty to fall back to the global renewal-period "
             "setting with no recorded amount.")
    subscription_payment_ids = fields.One2many(
        "otm.swm.subscription.payment", "member_id",
        string="Payment History")
    subscription_payment_count = fields.Integer(
        compute="_compute_subscription_payment_count")
    wallet_balance = fields.Monetary(
        currency_field="wallet_currency_id", default=0.0, readonly=True,
        help="What this member has left to spend on per-kg waste "
             "charges. Topped up by the plan's price on every Renew "
             "Subscription. Only relevant for a plan with Included Kg "
             "set (i.e. one with a per-kg rate) - flat plans never "
             "touch this.")
    wallet_currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id)

    @api.depends("subscription_active", "subscription_expiry")
    def _compute_subscription_valid(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.subscription_valid = bool(
                rec.subscription_active
                and (not rec.subscription_expiry
                     or rec.subscription_expiry >= today))

    def _compute_rfid_card_count(self):
        for rec in self:
            rec.rfid_card_count = len(rec.rfid_card_ids)

    def _compute_subscription_payment_count(self):
        for rec in self:
            rec.subscription_payment_count = len(rec.subscription_payment_ids)

    def action_renew_subscription(self):
        """Extend subscription_expiry using the assigned plan's duration
        and current price (falling back to the global renewal-period
        setting with no charge if no plan is assigned), extending from
        today - not from the old expiry, so a lapsed member renewing
        gets a fresh full period rather than back-dated coverage. Logs
        exactly what was charged, snapshotted, so later editing the
        plan's price never rewrites this history."""
        Payment = self.env["otm.swm.subscription.payment"]
        for rec in self:
            plan = rec.subscription_plan_id
            days = (plan.duration_days if plan else
                    self.env["res.config.settings"].swm_get_int(
                        "subscription_renewal_days", 30))
            today = fields.Date.context_today(rec)
            new_expiry = fields.Date.add(today, days=days)
            rec.write({
                "subscription_active": True,
                "subscription_expiry": new_expiry,
                "subscription_last_reminder_date": False,
                "wallet_balance": rec.wallet_balance + (
                    plan.price if plan else 0.0),
            })
            Payment.create({
                "member_id": rec.id,
                "plan_id": plan.id if plan else False,
                "plan_name": plan.name if plan else "(no plan / manual renewal)",
                "amount": plan.price if plan else 0.0,
                "currency_id": (plan.currency_id.id if plan
                                else self.env.company.currency_id.id),
                "payment_date": today,
                "period_start": today,
                "period_end": new_expiry,
            })
        return True

    def action_view_payment_history(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"Payment History — {self.name}",
            "res_model": "otm.swm.subscription.payment",
            "view_mode": "list,form",
            "domain": [("member_id", "=", self.id)],
        }

    def action_view_rfid_cards(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"RFID Cards — {self.name}",
            "res_model": "otm.swm.rfid.card",
            "view_mode": "list,form",
            "domain": [("member_id", "=", self.id)],
            "context": {"default_member_id": self.id},
        }

    @api.model
    def cron_send_subscription_reminders(self):
        """Nudge to renew: connected members whose subscription has
        lapsed, or is about to within the configured window, get a
        Telegram reminder. Runs daily but only actually messages
        someone once per pre-expiry window and roughly once a month
        while lapsed - subscription_last_reminder_date is what
        prevents this from becoming a daily spam message. Access
        itself is enforced live on every RFID tap regardless of
        whether a reminder was ever sent."""
        Settings = self.env["res.config.settings"]
        days_before = Settings.swm_get_int(
            "subscription_reminder_days_before", 5)
        today = fields.Date.context_today(self)
        soon = fields.Date.add(today, days=days_before)
        window_start = fields.Date.subtract(today, days=days_before)
        lapsed_repeat_after = fields.Date.subtract(today, days=30)

        candidates = self.search([
            ("subscription_expiry", "!=", False),
            ("subscription_expiry", "<=", soon),
            ("telegram_connected", "=", True),
        ])
        Bridge = self.env["software.telegram.message"].sudo()
        for member in candidates:
            last = member.subscription_last_reminder_date
            lapsed = member.subscription_expiry < today
            if lapsed:
                if last and last > lapsed_repeat_after:
                    continue  # already nagged this month
            else:
                if last and last >= window_start:
                    continue  # already reminded during this window
            text = (
                (f"⚠️ Your waste bin subscription for "
                 f"{member.association_id.name} lapsed on "
                 f"{member.subscription_expiry}. Your RFID card will "
                 f"not open bins until you renew. Please contact your "
                 f"association to renew.")
                if lapsed else
                (f"🔔 Your waste bin subscription for "
                 f"{member.association_id.name} expires on "
                 f"{member.subscription_expiry}. Renew soon to keep "
                 f"your RFID card working without interruption."))
            Bridge.send_direct(
                chat_id=member.telegram_chat_id, text=text,
                event_type="swm_subscription_reminder",
                res_model=self._name, res_id=member.id)
            member.subscription_last_reminder_date = today

    def action_sync_telegram_from_bot(self):
        """Pull the linked chat_id from the shared software_telegram bot
        (via this member's portal res.users) into this member's own
        fields. The member's Telegram fields stay the single interface
        the notification engine reads — this just keeps them in step
        with the shared bot's registry instead of maintaining a second,
        module-specific webhook and token flow. A no-op, not an error,
        when the member has no portal user or hasn't connected yet."""
        for rec in self:
            user = rec.sudo().user_id
            contact = user.sudo().telegram_contact_id if user else False
            if not contact:
                continue
            rec.sudo().write({
                "telegram_connected": True,
                "telegram_chat_id": contact.chat_id,
                "telegram_user_id": contact.chat_id,
                "telegram_username": contact.telegram_username or "",
                "telegram_connected_on": (
                    rec.telegram_connected_on or fields.Datetime.now()),
            })
        return True

    def action_disconnect_telegram(self):
        for rec in self:
            # Break the shared bot's link too (and rotate the link token)
            # — otherwise action_sync_telegram_from_bot would silently
            # reconnect this member from the still-linked res.users
            # contact the next time this page loads, and the member's
            # old QR/deep-link would still work to reconnect them.
            user = rec.sudo().user_id
            if user:
                user.sudo().action_disconnect_telegram()
                user.sudo().action_regenerate_telegram_link()
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
