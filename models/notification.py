# Part of Otomater. See LICENSE file for full copyright and licensing details.
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

TRIGGER_TYPES = [
    ("bin_nearly_full", "Bin Nearly Full"),
    ("bin_full", "Bin Full"),
    ("collection_pending", "Collection Pending"),
    ("collection_delayed", "Collection Delayed"),
    ("collection_completed", "Collection Completed / Bin Empty"),
    ("device_offline", "Device Offline"),
    ("device_online", "Device Back Online"),
    ("maintenance", "Maintenance Required"),
]

RECIPIENT_TYPES = [
    ("collection_staff", "Assigned Collection Staff"),
    ("supervisor", "Collection Supervisor"),
    ("association_manager", "Association Manager"),
    ("association_president", "Association President / Secretary"),
    ("association_members", "Association Members"),
    ("association_group", "Association Telegram Group"),
    ("corporation_officer", "Corporation / Municipality Officer"),
    ("default_group", "Default Telegram Group"),
    ("custom_chat", "Custom Telegram Chat ID"),
]


class SwmNotificationTemplate(models.Model):
    _name = "otm.swm.notification.template"
    _description = "Notification Template"
    _order = "name"

    name = fields.Char(required=True)
    body = fields.Text(
        required=True,
        help="Placeholders: {bin_code} {bin_name} {street} {association} "
             "{ward} {corporation} {fill}% {status} {time} {full_since} "
             "{request} {staff} {response_hours} {link}")
    active = fields.Boolean(default=True)

    def render(self, bin_rec, request=None):
        self.ensure_one()
        tz_now = fields.Datetime.context_timestamp(
            bin_rec, fields.Datetime.now())
        values = {
            "bin_code": bin_rec.code or "",
            "bin_name": bin_rec.name or "",
            "street": bin_rec.street_id.name or "",
            "association": bin_rec.association_id.name or "",
            "ward": bin_rec.ward_id.name or "",
            "corporation": bin_rec.corporation_id.name or "",
            "fill": round(bin_rec.fill_percentage or 0),
            "status": dict(bin_rec._fields["status"].selection).get(
                bin_rec.status, bin_rec.status),
            "time": tz_now.strftime("%d-%m-%Y %I:%M %p"),
            "full_since": fields.Datetime.context_timestamp(
                bin_rec, bin_rec.full_since).strftime("%d-%m-%Y %I:%M %p")
            if bin_rec.full_since else "",
            "request": request.name if request else "",
            "staff": (request.staff_id.name if request and request.staff_id
                      else bin_rec.staff_id.name or ""),
            "response_hours": round(request.response_hours, 1)
            if request and request.response_hours else 0,
            "link": bin_rec.public_url or "",
        }
        try:
            return self.body.format(**values)
        except (KeyError, IndexError, ValueError) as exc:
            _logger.warning("SWM template %s render error: %s", self.name, exc)
            return self.body


class SwmNotificationRule(models.Model):
    _name = "otm.swm.notification.rule"
    _description = "Notification / Escalation Rule"
    _order = "trigger_type, escalation_level, delay_number"

    name = fields.Char(required=True)
    trigger_type = fields.Selection(TRIGGER_TYPES, required=True, index=True)
    delay_number = fields.Integer(
        string="Delay Duration", default=0,
        help="0 = send immediately when the trigger occurs. For "
             "'Collection Delayed', delay is measured from the moment the "
             "bin was detected full.")
    delay_unit = fields.Selection([
        ("minutes", "Minutes"),
        ("hours", "Hours"),
        ("days", "Days"),
    ], default="hours", required=True)
    recipient_type = fields.Selection(RECIPIENT_TYPES, required=True)
    custom_chat_id = fields.Char(
        string="Custom Chat ID",
        groups="smart_waste_management.group_swm_manager")
    channel_telegram = fields.Boolean(string="Telegram", default=True)
    channel_internal = fields.Boolean(string="Internal Odoo Notification")
    channel_email = fields.Boolean(string="Email")
    template_id = fields.Many2one(
        "otm.swm.notification.template", required=True,
        string="Notification Template")
    escalation_level = fields.Integer(
        default=0,
        help="0 = normal notification. 1..n = escalation ladder for "
             "delayed collections.")
    recurring = fields.Boolean(
        string="Recurring Reminder",
        help="If set, this delayed rule re-fires every 'Recur Every' hours "
             "instead of firing once.")
    recur_every_hours = fields.Integer(string="Recur Every (hours)", default=6)
    active = fields.Boolean(default=True)

    def _delay_seconds(self):
        self.ensure_one()
        factor = {"minutes": 60, "hours": 3600, "days": 86400}[self.delay_unit]
        return (self.delay_number or 0) * factor

    # ------------------------------------------------------------------
    # Engine
    # ------------------------------------------------------------------
    @api.model
    def process_event(self, trigger, bin_rec, request=None):
        """Fire all immediate (delay == 0) rules for an event."""
        rules = self.search([
            ("trigger_type", "=", trigger),
            ("delay_number", "=", 0),
        ])
        for rule in rules:
            rule._fire(bin_rec, request=request, trigger=trigger)

    @api.model
    def process_delayed(self, request):
        """Called by cron for each open collection request: fire due
        'collection_delayed' rules, once per rule unless recurring."""
        now = fields.Datetime.now()
        elapsed = (now - request.full_detected_time).total_seconds()
        rules = self.search([
            ("trigger_type", "=", "collection_delayed"),
        ], order="escalation_level, delay_number")
        Log = self.env["otm.swm.notification.log"].sudo()
        for rule in rules:
            delay = rule._delay_seconds()
            if delay <= 0 or elapsed < delay:
                continue
            if rule in request.fired_rule_ids:
                if not rule.recurring:
                    continue
                last = Log.search([
                    ("rule_id", "=", rule.id),
                    ("request_id", "=", request.id),
                ], order="id desc", limit=1)
                gap = max(1, rule.recur_every_hours or 6) * 3600
                if last and (now - last.create_date).total_seconds() < gap:
                    continue
            rule._fire(request.bin_id, request=request,
                       trigger="collection_delayed")
            request.sudo().write({
                "fired_rule_ids": [(4, rule.id)],
                "escalation_level": max(request.escalation_level,
                                        rule.escalation_level),
            })

    def _fire(self, bin_rec, request=None, trigger=None):
        self.ensure_one()
        message = self.template_id.render(bin_rec, request=request)
        recipients = self._resolve_recipients(bin_rec, request=request,
                                              trigger=trigger)
        Log = self.env["otm.swm.notification.log"].sudo()
        Telegram = self.env["otm.swm.telegram"].sudo()
        if self.channel_telegram:
            if not recipients:
                Log.create(self._log_vals(
                    bin_rec, request, "telegram", "", message, "skipped",
                    "No Telegram recipient resolved"))
            for chat_id, label in recipients:
                ok, detail = Telegram.send_message(chat_id, message)
                Log.create(self._log_vals(
                    bin_rec, request, "telegram", label or chat_id, message,
                    "sent" if ok else "failed", detail))
        if self.channel_internal:
            target = request or bin_rec
            try:
                target.message_post(body=message.replace("\n", "<br/>"))
                Log.create(self._log_vals(
                    bin_rec, request, "internal", "Chatter", message, "sent"))
            except Exception as exc:  # noqa: BLE001 - never break sensor tx
                _logger.exception("SWM internal notification failed")
                Log.create(self._log_vals(
                    bin_rec, request, "internal", "Chatter", message,
                    "failed", str(exc)))
        if self.channel_email:
            self._send_emails(bin_rec, request, message, Log)

    def _resolve_recipients(self, bin_rec, request=None, trigger=None):
        """Return list of (telegram_chat_id, label)."""
        self.ensure_one()
        Settings = self.env["res.config.settings"]
        result = []
        rtype = self.recipient_type
        staff = (request.staff_id if request and request.staff_id
                 else bin_rec.staff_id or bin_rec.sudo()._resolve_staff())
        if rtype == "collection_staff" and staff:
            if staff.sudo().telegram_chat_id:
                result.append((staff.sudo().telegram_chat_id,
                               f"Staff: {staff.name}"))
        elif rtype == "supervisor":
            sup = staff.supervisor_id if staff else self.env["otm.swm.staff"]
            if not sup:
                sup = self.env["otm.swm.staff"].sudo().search(
                    [("is_supervisor", "=", True), ("active", "=", True)],
                    limit=1)
            if sup and sup.sudo().telegram_chat_id:
                result.append((sup.sudo().telegram_chat_id,
                               f"Supervisor: {sup.name}"))
        elif rtype == "association_manager":
            manager = bin_rec.association_id.manager_user_id
            member = self.env["otm.swm.association.member"].sudo().search(
                [("user_id", "=", manager.id)], limit=1) if manager else None
            if member and member.telegram_chat_id:
                result.append((member.telegram_chat_id,
                               f"Manager: {member.name}"))
        elif rtype == "association_president":
            assoc = bin_rec.association_id
            partners = assoc.president_id | assoc.secretary_id
            members = self.env["otm.swm.association.member"].sudo().search([
                ("partner_id", "in", partners.ids),
                ("telegram_connected", "=", True),
            ])
            result += [(m.telegram_chat_id, f"Office Bearer: {m.name}")
                       for m in members if m.telegram_chat_id]
        elif rtype == "association_members":
            pref_field = {
                "bin_full": "notify_bin_full",
                "collection_pending": "notify_bin_full",
                "collection_delayed": "notify_delayed",
                "collection_completed": "notify_collected",
            }.get(trigger or self.trigger_type)
            domain = [("association_id", "=", bin_rec.association_id.id),
                      ("telegram_connected", "=", True),
                      ("active", "=", True)]
            if pref_field:
                domain.append((pref_field, "=", True))
            members = self.env["otm.swm.association.member"].sudo().search(
                domain)
            # Street-level preference: full/collected alerts go to the
            # bin's street members plus members without a street.
            if bin_rec.street_id and pref_field in ("notify_bin_full",
                                                    "notify_collected"):
                members = members.filtered(
                    lambda m: not m.street_id
                    or m.street_id == bin_rec.street_id)
            result += [(m.telegram_chat_id, f"Member: {m.name}")
                       for m in members if m.telegram_chat_id]
        elif rtype == "association_group":
            chat = bin_rec.association_id.sudo().telegram_group_chat_id
            if chat:
                result.append((chat,
                               f"Group: {bin_rec.association_id.name}"))
        elif rtype == "corporation_officer":
            officer = bin_rec.corporation_id.officer_id
            member = self.env["otm.swm.association.member"].sudo().search(
                [("user_id", "=", officer.id)], limit=1) if officer else None
            staff_off = self.env["otm.swm.staff"].sudo().search(
                [("user_id", "=", officer.id)], limit=1) if officer else None
            chat = ((member and member.telegram_chat_id)
                    or (staff_off and staff_off.telegram_chat_id))
            if chat:
                result.append((chat, f"Officer: {officer.name}"))
        elif rtype == "default_group":
            chat = Settings.swm_get_str("telegram_default_group")
            if chat:
                result.append((chat, "Default Group"))
        elif rtype == "custom_chat" and self.sudo().custom_chat_id:
            result.append((self.sudo().custom_chat_id, "Custom Chat"))
        return result

    def _send_emails(self, bin_rec, request, message, Log):
        self.ensure_one()
        emails = []
        if self.recipient_type == "corporation_officer" \
                and bin_rec.corporation_id.email:
            emails.append(bin_rec.corporation_id.email)
        elif self.recipient_type in ("association_manager",
                                     "association_president") \
                and bin_rec.association_id.email:
            emails.append(bin_rec.association_id.email)
        for email in emails:
            try:
                self.env["mail.mail"].sudo().create({
                    "subject": f"[SWM] {bin_rec.code} — {self.name}",
                    "email_to": email,
                    "body_html": message.replace("\n", "<br/>"),
                }).send(raise_exception=False)
                Log.create(self._log_vals(
                    bin_rec, request, "email", email, message, "sent"))
            except Exception as exc:  # noqa: BLE001
                _logger.exception("SWM email notification failed")
                Log.create(self._log_vals(
                    bin_rec, request, "email", email, message, "failed",
                    str(exc)))

    def _log_vals(self, bin_rec, request, channel, recipient, message,
                  status, detail=None):
        return {
            "rule_id": self.id,
            "trigger_type": self.trigger_type,
            "bin_id": bin_rec.id,
            "request_id": request.id if request else False,
            "channel": channel,
            "recipient": recipient,
            "message": message,
            "state": status,
            "detail": detail,
        }


class SwmNotificationLog(models.Model):
    _name = "otm.swm.notification.log"
    _description = "Notification Log"
    _order = "id desc"

    rule_id = fields.Many2one("otm.swm.notification.rule", string="Rule",
                              index=True)
    trigger_type = fields.Selection(TRIGGER_TYPES, string="Trigger")
    bin_id = fields.Many2one("otm.swm.bin", string="Smart Bin", index=True)
    request_id = fields.Many2one("otm.swm.collection.request",
                                 string="Collection Request", index=True)
    channel = fields.Selection([
        ("telegram", "Telegram"),
        ("internal", "Internal"),
        ("email", "Email"),
    ])
    recipient = fields.Char()
    message = fields.Text()
    state = fields.Selection([
        ("sent", "Sent"),
        ("failed", "Failed"),
        ("skipped", "Skipped"),
    ], string="Delivery Status", index=True)
    detail = fields.Text(string="External Response / Error")
