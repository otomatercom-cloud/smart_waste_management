# Part of Otomater. See LICENSE file for full copyright and licensing details.
import logging
import secrets
from urllib.parse import quote

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import _

_logger = logging.getLogger(__name__)

BIN_STATUSES = [
    ("available", "Available"),
    ("nearly_full", "Nearly Full"),
    ("full", "Full"),
    ("collection_pending", "Collection Pending"),
    ("collection_in_progress", "Collection In Progress"),
    ("collected", "Empty / Collected"),
    ("offline", "Offline"),
    ("maintenance", "Maintenance"),
]

# Statuses that mean "waste level is at/above full and waiting to be handled"
FULL_LIKE = ("full", "collection_pending", "collection_in_progress")


class SwmBin(models.Model):
    _name = "otm.swm.bin"
    _description = "Smart Waste Bin"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "code"
    _rec_name = "display_label"

    name = fields.Char(string="Bin Name", required=True, tracking=True)
    code = fields.Char(
        string="Bin Code", readonly=True, copy=False, index=True,
        default=lambda self: _("New"))
    display_label = fields.Char(
        compute="_compute_display_label", store=True)

    association_id = fields.Many2one(
        "otm.swm.association", required=True, string="Association",
        tracking=True)
    street_id = fields.Many2one(
        "otm.swm.street", string="Street",
        domain="[('association_id', '=', association_id)]", tracking=True)
    ward_id = fields.Many2one(
        related="association_id.ward_id", store=True, readonly=True)
    zone_id = fields.Many2one(
        related="association_id.zone_id", store=True, readonly=True)
    corporation_id = fields.Many2one(
        related="association_id.corporation_id", store=True, readonly=True,
        string="Corporation / Municipality")

    latitude = fields.Float(digits=(10, 7))
    longitude = fields.Float(digits=(10, 7))
    location_note = fields.Char(string="Location Description")
    installation_date = fields.Date()
    capacity_liters = fields.Float(string="Capacity (L)")
    bin_height_cm = fields.Float(
        string="Bin Height (cm)",
        help="Used to derive fill %% from ultrasonic distance when the "
             "device sends only distance_cm.")

    # Device
    device_id = fields.Char(string="ESP32 Device ID", copy=False, index=True)
    api_token = fields.Char(
        string="API Device Token", copy=False,
        groups="smart_waste_management.group_swm_manager",
        default=lambda self: secrets.token_urlsafe(32))
    device_online = fields.Boolean(string="Device Online", readonly=True)
    last_communication = fields.Datetime(
        string="Last Device Communication", readonly=True)
    battery_level = fields.Float(string="Battery Level (%)", readonly=True)
    signal_strength = fields.Float(string="Signal Strength (dBm)", readonly=True)

    # Live sensor state
    current_distance_cm = fields.Float(
        string="Current Distance (cm)", readonly=True)
    fill_percentage = fields.Float(
        string="Fill Percentage", readonly=True, tracking=True,
        aggregator="avg")
    last_reading_time = fields.Datetime(
        string="Last Sensor Reading", readonly=True)
    status = fields.Selection(
        BIN_STATUSES, default="available", required=True, tracking=True,
        index=True)
    last_status_change = fields.Datetime(readonly=True)
    pending_status_candidate = fields.Char(
        readonly=True, copy=False,
        help="Candidate critical status awaiting confirmation by "
             "consecutive sensor readings (noise debounce).")
    pending_status_count = fields.Integer(readonly=True, copy=False)
    full_since = fields.Datetime(readonly=True, copy=False)
    last_emptied_time = fields.Datetime(readonly=True, copy=False)
    collection_requested_time = fields.Datetime(readonly=True, copy=False)
    collection_completed_time = fields.Datetime(readonly=True, copy=False)

    staff_id = fields.Many2one(
        "otm.swm.staff", string="Assigned Collection Staff", tracking=True)
    active = fields.Boolean(default=True)

    reading_ids = fields.One2many(
        "otm.swm.sensor.reading", "bin_id", string="Sensor Readings")
    collection_request_ids = fields.One2many(
        "otm.swm.collection.request", "bin_id", string="Collection Requests")
    open_request_id = fields.Many2one(
        "otm.swm.collection.request", compute="_compute_open_request",
        string="Open Collection Request")
    complaint_ids = fields.One2many(
        "otm.swm.complaint", "bin_id", string="Complaints")

    public_url = fields.Char(compute="_compute_public_url", string="Public Page")
    qr_image_url = fields.Char(compute="_compute_public_url", string="QR Code")
    details_url = fields.Char(
        compute="_compute_public_url", string="Public Details Page",
        help="Full public status page: live fill, device connectivity, "
             "location, assigned staff, and history stats. Separate from "
             "the citizen QR page so it can carry richer detail.")
    details_qr_image_url = fields.Char(
        compute="_compute_public_url", string="Details Page QR Code")
    staff_qr_url = fields.Char(
        compute="_compute_public_url", string="Staff Collect Page",
        help="Login-protected page for collection staff to approve an "
             "emptied bin. Print this QR inside the lid.")
    staff_qr_image_url = fields.Char(
        compute="_compute_public_url", string="Staff QR Code")

    # ---- RFID lock / weight sensor (optional, settings-gated) ----
    current_weight_kg = fields.Float(
        string="Current Weight (kg)", digits=(6, 2), readonly=True)
    last_weight_time = fields.Datetime(readonly=True)
    last_access_member_id = fields.Many2one(
        "otm.swm.association.member", readonly=True,
        string="Last Opened By (Member)",
        help="Set only when a member card opened this bin.")
    last_access_staff_id = fields.Many2one(
        "otm.swm.staff", readonly=True,
        string="Last Opened By (Staff)",
        help="Set only when a staff/supervisor card opened this bin - "
             "including opens while the bin was full, which a member "
             "card cannot do.")
    last_access_name = fields.Char(
        readonly=True,
        help="Name of whoever's card most recently opened this bin, "
             "member or staff - use this for a simple display; the two "
             "fields above are for filtering by holder type.")
    last_access_time = fields.Datetime(readonly=True)
    active_session_log_id = fields.Many2one(
        "otm.swm.bin.access.log", readonly=True, copy=False,
        help="The still-open visit (granted tap, session window not "
             "yet closed) whose weight_deposited_kg hasn't been "
             "finalised. Empty when no one's currently mid-visit.")
    session_deadline = fields.Datetime(readonly=True, copy=False)
    access_log_ids = fields.One2many(
        "otm.swm.bin.access.log", "bin_id", string="Access Log")
    access_log_count = fields.Integer(compute="_compute_access_log_count")

    def _compute_access_log_count(self):
        for rec in self:
            rec.access_log_count = len(rec.access_log_ids)

    def action_view_access_log(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"Access Log — {self.code}",
            "res_model": "otm.swm.bin.access.log",
            "view_mode": "list,form",
            "domain": [("bin_id", "=", self.id)],
        }

    _sql_constraints = [
        ("code_uniq", "unique(code)", "Bin code must be unique."),
        ("device_uniq", "unique(device_id)",
         "This ESP32 Device ID is already linked to another bin."),
    ]

    # ------------------------------------------------------------------
    # CRUD / computes
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("code") or vals["code"] == _("New"):
                vals["code"] = self.env["ir.sequence"].next_by_code(
                    "otm.swm.bin") or "/"
        return super().create(vals_list)

    @api.depends("name", "code")
    def _compute_display_label(self):
        for rec in self:
            rec.display_label = (
                f"{rec.code} — {rec.name}" if rec.code and rec.name
                else rec.name or rec.code or "")

    def _compute_open_request(self):
        Request = self.env["otm.swm.collection.request"]
        for rec in self:
            rec.open_request_id = Request.search(
                [("bin_id", "=", rec.id),
                 ("state", "in", ("new", "assigned", "accepted",
                                  "in_progress"))],
                order="id desc", limit=1)

    def _compute_public_url(self):
        base = self.env["ir.config_parameter"].sudo().get_param(
            "web.base.url", "")
        for rec in self:
            url = f"{base}/waste/bin/{quote(rec.code or '')}"
            rec.public_url = url
            rec.qr_image_url = (
                f"/report/barcode/?barcode_type=QR&value={quote(url, safe='')}"
                f"&width=220&height=220")
            details_url = f"{url}/details"
            rec.details_url = details_url
            rec.details_qr_image_url = (
                f"/report/barcode/?barcode_type=QR"
                f"&value={quote(details_url, safe='')}"
                f"&width=220&height=220")
            staff_url = f"{url}/collect"
            rec.staff_qr_url = staff_url
            rec.staff_qr_image_url = (
                f"/report/barcode/?barcode_type=QR"
                f"&value={quote(staff_url, safe='')}"
                f"&width=220&height=220")

    def action_regenerate_token(self):
        for rec in self:
            rec.api_token = secrets.token_urlsafe(32)
        return True

    def action_set_maintenance(self):
        self._change_status("maintenance", reason="Manual: maintenance")
        self.env["otm.swm.notification.rule"].sudo().process_event(
            "maintenance", self)
        return True

    def action_clear_maintenance(self):
        for rec in self.filtered(lambda b: b.status == "maintenance"):
            rec._apply_fill(rec.fill_percentage, force=True)
        return True

    # ------------------------------------------------------------------
    # Threshold helpers
    # ------------------------------------------------------------------
    @api.model
    def _thresholds(self):
        Settings = self.env["res.config.settings"]
        return {
            "nearly": Settings.swm_get_int("threshold_nearly_full", 80),
            "full": Settings.swm_get_int("threshold_full", 95),
            "empty": Settings.swm_get_int("threshold_empty", 25),
            "hyst": Settings.swm_get_int("hysteresis", 3),
        }

    def _status_from_fill(self, fill, force=False):
        """Return target status for a fill %, honouring hysteresis against
        the current status so 94→96→94→96 flutter cannot flip repeatedly."""
        self.ensure_one()
        t = self._thresholds()
        current = self.status
        if not force:
            # Empty detection while waiting for / doing collection.
            if current in FULL_LIKE and fill <= t["empty"]:
                return "collected"
            # Hysteresis: once full-like, stay until below full - hyst.
            if current in FULL_LIKE and fill >= t["full"] - t["hyst"]:
                return current if current != "full" else "full"
            # Hysteresis leaving nearly_full downwards.
            if current == "nearly_full" and fill >= t["nearly"] - t["hyst"]:
                if fill >= t["full"]:
                    return "full"
                return "nearly_full"
        if fill >= t["full"]:
            return "full"
        if fill >= t["nearly"]:
            return "nearly_full"
        return "available"

    # ------------------------------------------------------------------
    # Sensor entry point (called sudo() from the IoT controller / tests)
    # ------------------------------------------------------------------
    def process_reading(self, distance_cm=None, fill_percentage=None,
                        device_status=None, battery_level=None,
                        signal_strength=None, weight_kg=None, raw=None):
        self.ensure_one()
        now = fields.Datetime.now()
        Settings = self.env["res.config.settings"]

        # Close out any prior visit whose window has already elapsed,
        # and feed a currently-open one if this reading arrives within
        # its window - a status ping can carry weight just as well as
        # an RFID tap can.
        self._close_stale_session()
        if weight_kg is not None and Settings.swm_get_bool(
                "weight_capture_enabled", False):
            self.write({
                "current_weight_kg": weight_kg,
                "last_weight_time": now,
            })
            if self.active_session_log_id:
                self.active_session_log_id.session_end_weight_kg = weight_kg

        if fill_percentage is None and distance_cm is not None \
                and self.bin_height_cm:
            fill_percentage = max(
                0.0, min(100.0,
                         (1 - distance_cm / self.bin_height_cm) * 100.0))
        if fill_percentage is None:
            return {"result": "error",
                    "message": "fill_percentage or (distance_cm + bin "
                               "height) required"}
        fill_percentage = max(0.0, min(100.0, float(fill_percentage)))

        was_offline = self.status == "offline" or not self.device_online
        comm_vals = {
            "device_online": device_status != "offline",
            "last_communication": now,
        }
        if battery_level is not None:
            comm_vals["battery_level"] = battery_level
        if signal_strength is not None:
            comm_vals["signal_strength"] = signal_strength

        # Storage policy — three independent guards decide whether this
        # reading earns a DB row (the live status engine always runs):
        # 1. identical values inside the dedupe window are never stored
        # 2. rows are throttled to one per min_storage_seconds ...
        # 3. ... unless the fill moved by at least storage_delta %,
        #    which is always stored immediately (captures real events).
        dedupe_min = Settings.swm_get_int("dedupe_minutes", 10)
        min_storage_s = Settings.swm_get_int("min_storage_seconds", 60)
        storage_delta = Settings.swm_get_int("storage_delta", 5)
        last = self.env["otm.swm.sensor.reading"].search(
            [("bin_id", "=", self.id)], order="id desc", limit=1)
        elapsed = ((now - last.create_date).total_seconds()
                   if last and last.create_date else None)
        delta = (abs((last.fill_percentage or 0) - fill_percentage)
                 if last else None)
        identical = bool(
            last and dedupe_min > 0
            and delta is not None and delta < 0.5
            and (distance_cm is None
                 or abs((last.distance_cm or 0) - distance_cm) < 0.5)
            and elapsed is not None and elapsed < dedupe_min * 60)
        throttled = bool(
            last and min_storage_s > 0
            and elapsed is not None and elapsed < min_storage_s
            and delta is not None and delta < storage_delta)
        duplicate = identical or throttled

        if not duplicate:
            self.env["otm.swm.sensor.reading"].create({
                "bin_id": self.id,
                "distance_cm": distance_cm,
                "fill_percentage": fill_percentage,
                "device_status": device_status or "online",
                "battery_level": battery_level,
                "signal_strength": signal_strength,
                "raw_payload": raw,
            })
        # Live fields always reflect the latest reading, stored or not —
        # the staff QR approval and dashboards rely on fresh values.
        comm_vals.update({
            "current_distance_cm": distance_cm,
            "fill_percentage": fill_percentage,
            "last_reading_time": now,
        })
        self.write(comm_vals)

        if was_offline and comm_vals["device_online"]:
            self.env["otm.swm.notification.rule"].sudo().process_event(
                "device_online", self)

        status_result = self._apply_fill(fill_percentage)
        return {
            "result": "ok",
            "bin_code": self.code,
            "fill_percentage": fill_percentage,
            "status": self.status,
            "duplicate_reading": duplicate,
            "status_changed": status_result["changed"],
        }

    def _apply_fill(self, fill, force=False):
        """Run the status engine for a fill value. Returns dict."""
        self.ensure_one()
        if self.status == "maintenance" and not force:
            return {"changed": False}
        new_status = self._status_from_fill(fill, force=force)
        if new_status == self.status:
            if self.pending_status_candidate:
                self.write({"pending_status_candidate": False,
                            "pending_status_count": 0})
            return {"changed": False}
        # Noise debounce: entering a critical state (full → creates a
        # collection request; collected → completes one) requires N
        # consecutive readings agreeing, so a single stray ultrasonic
        # echo cannot fire requests, completions, or Telegram alerts.
        confirm = self.env["res.config.settings"].swm_get_int(
            "status_confirm_count", 2)
        if not force and confirm > 1 and new_status in ("full", "collected"):
            if self.pending_status_candidate == new_status:
                count = self.pending_status_count + 1
            else:
                count = 1
            if count < confirm:
                self.write({"pending_status_candidate": new_status,
                            "pending_status_count": count})
                return {"changed": False, "pending": new_status,
                        "pending_count": count}
        if self.pending_status_candidate:
            self.write({"pending_status_candidate": False,
                        "pending_status_count": 0})
        old = self.status
        if new_status == "full" and old not in FULL_LIKE:
            self._on_bin_full()
        elif new_status == "collected":
            self._on_bin_collected()
        elif new_status == "nearly_full" and old in ("available", "collected",
                                                     "offline", "maintenance"):
            self._change_status("nearly_full")
            self.env["otm.swm.notification.rule"].sudo().process_event(
                "bin_nearly_full", self)
        else:
            self._change_status(new_status)
        return {"changed": True, "from": old, "to": self.status}

    def _change_status(self, status, reason=None):
        for rec in self:
            rec.write({"status": status,
                       "last_status_change": fields.Datetime.now()})
            if reason:
                rec.message_post(body=reason)

    # ------------------------------------------------------------------
    # Full / collected workflows
    # ------------------------------------------------------------------
    def _on_bin_full(self):
        self.ensure_one()
        now = fields.Datetime.now()
        self.write({"status": "full", "full_since": now,
                    "last_status_change": now,
                    "collection_completed_time": False})
        # A bin can transition into "full" from offline/maintenance while
        # a request is still open (device silence → offline cron → device
        # returns). Never stack a second request on an open one.
        existing = self.open_request_id
        if existing:
            self.write({"status": "collection_pending"})
            return existing
        request = self.env["otm.swm.collection.request"].sudo().create({
            "bin_id": self.id,
            "staff_id": self._resolve_staff().id or False,
            "full_detected_time": now,
        })
        self.write({"collection_requested_time": now,
                    "status": "collection_pending"})
        self.env["otm.swm.notification.rule"].sudo().process_event(
            "bin_full", self, request=request)
        self.env["otm.swm.notification.rule"].sudo().process_event(
            "collection_pending", self, request=request)
        return request

    @api.model
    def get_dashboard_thresholds(self):
        """Small, safely-RPC-able bundle of settings the OWL dashboard
        needs. Reads through here rather than calling res.config.settings
        methods directly from JS, since that model's own ACL is
        normally restricted to users who can access Settings - this
        model is already readable by anyone who can see the dashboard."""
        raw = self.env["ir.config_parameter"].sudo().get_param(
            "smart_waste_management.heavy_weight_threshold_kg", "10")
        try:
            threshold = float(raw)
        except (TypeError, ValueError):
            threshold = 10.0
        return {"heavy_weight_threshold_kg": threshold}

    def _finalize_session(self, log):
        """Compute the deposited weight for one visit, bill it against
        the member's wallet if applicable, and clear it as the bin's
        active session. Shared by the deadline-based lazy/cron close
        and the device's explicit close_rfid_session() call."""
        self.ensure_one()
        deposited = max(
            0.0, log.session_end_weight_kg - log.session_start_weight_kg)
        charge = 0.0
        balance_after = log.member_id.wallet_balance if log.member_id else 0.0
        if log.member_id and log.billing_rate_per_kg:
            charge = round(deposited * log.billing_rate_per_kg, 2)
            log.member_id.wallet_balance -= charge
            balance_after = log.member_id.wallet_balance
        log.write({
            "weight_deposited_kg": deposited,
            "amount_charged": charge,
            "wallet_balance_after": balance_after,
            "session_closed": True,
        })
        self.write({
            "active_session_log_id": False,
            "session_deadline": False,
        })
        if charge:
            self._send_billing_receipt(log)
        return log

    def _send_billing_receipt(self, log):
        """Telegram a connected member the moment they're actually
        billed: kg deposited, amount charged, new balance. Only called
        when a real charge happened - never for staff visits (their
        billing_rate_per_kg is always 0) or flat/unmetered plans."""
        Settings = self.env["res.config.settings"]
        if not Settings.swm_get_bool("billing_receipt_enabled", True):
            return
        member = log.member_id
        if not member or not member.telegram_connected:
            return
        text = (
            f"🗑️ Bin {log.bin_code}\n"
            f"Deposited: {log.weight_deposited_kg:.2f} kg\n"
            f"Charged: {log.currency_id.symbol}{log.amount_charged:.2f}\n"
            f"Balance: {log.currency_id.symbol}{log.wallet_balance_after:.2f}")
        self.env["software.telegram.message"].sudo().send_direct(
            chat_id=member.telegram_chat_id, text=text,
            event_type="swm_billing_receipt",
            res_model="otm.swm.bin.access.log", res_id=log.id)

    def _close_stale_session(self):
        """If this bin has an open visit whose window has passed,
        finalise it. Called opportunistically at the start of both
        check_rfid_access and process_reading, plus a safety-net cron,
        so a session closes within moments of its deadline even if the
        device never explicitly closes it (see close_rfid_session for
        the normal, immediate path a well-behaved device should use)."""
        self.ensure_one()
        if not self.active_session_log_id:
            return
        if self.session_deadline and fields.Datetime.now() < self.session_deadline:
            return  # still within the window - nothing to close yet
        self._finalize_session(self.active_session_log_id)

    def close_rfid_session(self, weight_kg=None):
        """Called by the device the moment it physically re-locks (e.g.
        at the end of its fixed hold-open timer), instead of waiting
        for the session_deadline to lazily elapse. Finalises NOW,
        regardless of whether the window has technically passed yet,
        and returns the bill so the device can show it immediately -
        this is the path that makes an OLED "your bill / balance"
        screen possible right when the lid closes.

        Safe to call with no session open (e.g. a staff visit, or
        weight capture was off) - returns has_session: False rather
        than raising."""
        self.ensure_one()
        if weight_kg is not None:
            Settings = self.env["res.config.settings"]
            if Settings.swm_get_bool("weight_capture_enabled", False):
                self.write({
                    "current_weight_kg": weight_kg,
                    "last_weight_time": fields.Datetime.now(),
                })
                if self.active_session_log_id:
                    self.active_session_log_id.session_end_weight_kg = weight_kg
        if not self.active_session_log_id:
            return {"has_session": False}
        log = self._finalize_session(self.active_session_log_id)
        return {
            "has_session": True,
            "weight_deposited_kg": log.weight_deposited_kg,
            "amount_charged": log.amount_charged,
            "wallet_balance": log.wallet_balance_after,
            "member_name": log.holder_name,
        }

    @api.model
    def cron_close_stale_rfid_sessions(self):
        """Safety net: closes any bin's open visit whose window has
        already passed, even if the device never calls
        close_rfid_session and no further tap or status ping arrives
        to trigger the lazy-close either. Cheap - only touches bins
        with a session actually open past its deadline."""
        stale = self.search([
            ("active_session_log_id", "!=", False),
            ("session_deadline", "<", fields.Datetime.now()),
        ])
        for rec in stale:
            rec._close_stale_session()

    def check_rfid_access(self, card_uid, weight_kg=None):
        """Called by the IoT controller the instant a card is tapped.
        Returns a dict the ESP32 uses to decide whether to actuate the
        lock: {"access": "granted"|"denied", "reason": ..., ...}.
        Every tap is logged (bin_access_log) except when the RFID
        feature is globally switched off, in which case the lock is a
        no-op passthrough and nothing is recorded.

        Member cards are denied while the bin is full-like (Full /
        Collection Pending / Collection In Progress) when the "Lock
        Full Bins to Staff Only" setting is on - only a staff or
        supervisor card opens it in that state, so a collector can
        service and empty it without residents adding more waste to an
        already-full bin in the meantime."""
        self.ensure_one()
        Settings = self.env["res.config.settings"]
        now = fields.Datetime.now()

        # Close out any prior visit whose window has already elapsed
        # before doing anything else with this tap.
        self._close_stale_session()

        weight_capture_on = Settings.swm_get_bool(
            "weight_capture_enabled", False)
        # Weight capture is independent of the lock feature - a bin can
        # have a load cell without RFID, or vice versa. This also feeds
        # an in-progress session if one is still open (e.g. the reading
        # arrived via /bin/status instead of a fresh tap).
        if weight_kg is not None and weight_capture_on:
            self.write({
                "current_weight_kg": weight_kg,
                "last_weight_time": now,
            })
            if self.active_session_log_id:
                self.active_session_log_id.session_end_weight_kg = weight_kg

        if not Settings.swm_get_bool("rfid_enabled", False):
            # Feature off: always open, no card/subscription checks, no
            # log entry - this bin behaves exactly as it did before the
            # lock was ever installed.
            return {"access": "granted", "reason": "rfid_feature_disabled"}

        Card = self.env["otm.swm.rfid.card"].sudo()
        card = Card.search([("card_uid", "=", card_uid)], limit=1)
        member = card.member_id if card else self.env[
            "otm.swm.association.member"]
        staff = card.staff_id if card else self.env["otm.swm.staff"]
        is_staff_card = bool(card and card.holder_type == "staff")
        bin_is_full_like = self.status in FULL_LIKE
        lock_when_full = Settings.swm_get_bool("lock_when_full_enabled", True)

        granted = False
        reason = "card_unknown"
        holder_name = ""
        effective_rate = 0.0
        if not card:
            reason = "card_unknown"
        elif not card.active:
            reason = "card_inactive"
        elif is_staff_card:
            # Staff/supervisor cards always open the bin - including
            # while full, which is precisely how they service it - and
            # are never subject to subscription enforcement or wallet
            # billing at all.
            granted = True
            reason = "granted"
            holder_name = staff.name
        elif bin_is_full_like and lock_when_full:
            granted = False
            reason = "bin_full_staff_only"
        elif Settings.swm_get_bool("subscription_enforcement_enabled", True) \
                and not member.subscription_valid:
            reason = "subscription_expired"
        else:
            plan = member.subscription_plan_id
            effective_rate = plan.rate_per_kg if plan else 0.0
            wallet_billed_plan = bool(plan and plan.rate_per_kg)
            wallet_billing_on = Settings.swm_get_bool(
                "wallet_billing_enabled", True)
            low_threshold = Settings.swm_get_float(
                "wallet_low_balance_threshold", 0.0)
            if (wallet_billed_plan and wallet_billing_on
                    and member.wallet_balance <= low_threshold):
                reason = "balance_low"
            else:
                granted = True
                reason = "granted"
                holder_name = member.name
                if not wallet_billing_on:
                    effective_rate = 0.0  # billing off: never charge

        start_weight = weight_kg if weight_kg is not None \
            else self.current_weight_kg
        log = self.env["otm.swm.bin.access.log"].sudo().create({
            "bin_id": self.id,
            "card_uid": card_uid,
            "card_id": card.id if card else False,
            "member_id": member.id if member else False,
            "staff_id": staff.id if staff else False,
            "holder_name": holder_name or (card.holder_name if card else ""),
            "granted": granted,
            "deny_reason": False if granted else reason,
            "weight_kg": weight_kg if weight_kg is not None else 0.0,
            "session_start_weight_kg": start_weight,
            "session_end_weight_kg": start_weight,
            "billing_rate_per_kg": effective_rate if granted else 0.0,
        })

        if granted:
            window = Settings.swm_get_int("session_window_seconds", 30)
            self.write({
                "last_access_member_id": member.id if not is_staff_card
                                         else False,
                "last_access_staff_id": staff.id if is_staff_card else False,
                "last_access_name": holder_name,
                "last_access_time": now,
                # Open a session ONLY when weight capture is actually
                # on - no point tracking a window with nothing to sum.
                "active_session_log_id": log.id if weight_capture_on else False,
                "session_deadline": (
                    fields.Datetime.add(now, seconds=window)
                    if weight_capture_on else False),
            })
        else:
            log.session_closed = True  # denied taps never open a session

        return {
            "access": "granted" if granted else "denied",
            "reason": reason,
            "member_name": holder_name,
            "wallet_balance": (
                member.wallet_balance if member and not is_staff_card
                else None),
        }

    def _resolve_staff(self):
        """Bin-level assignment wins, then street, association, ward,
        corporation level staff assignments."""
        self.ensure_one()
        if self.staff_id and self.staff_id.active:
            return self.staff_id
        Staff = self.env["otm.swm.staff"].sudo()
        domains = [
            [("bin_ids", "in", self.ids)],
            [("street_ids", "in", self.street_id.ids)] if self.street_id else None,
            [("association_ids", "in", self.association_id.ids)],
            [("ward_ids", "in", self.ward_id.ids)] if self.ward_id else None,
            [("corporation_ids", "in", self.corporation_id.ids)]
            if self.corporation_id else None,
        ]
        for dom in domains:
            if dom is None:
                continue
            staff = Staff.search(dom + [("active", "=", True)], limit=1)
            if staff:
                return staff
        return Staff.browse()

    def _on_bin_collected(self):
        self.ensure_one()
        now = fields.Datetime.now()
        request = self.open_request_id
        if request:
            request.sudo().action_mark_done(sensor_confirmed=True)
        self.write({
            "status": "collected",
            "last_status_change": now,
            "last_emptied_time": now,
            "collection_completed_time": now,
            "full_since": False,
        })
        self.env["otm.swm.notification.rule"].sudo().process_event(
            "collection_completed", self, request=request)

    def qr_confirm_collection(self):
        """Staff scanned the collect QR and asks to approve the bin as
        emptied. Only approved when the sensor corroborates: a fresh
        reading at or below the empty threshold. Returns a dict with
        ok + a human message for the page."""
        self.ensure_one()
        t = self._thresholds()
        now = fields.Datetime.now()
        Settings = self.env["res.config.settings"]

        if self.status == "maintenance":
            return {"ok": False, "reason": "maintenance",
                    "message": _("Bin is under maintenance — approval is "
                                 "disabled until maintenance is cleared.")}

        # Reading freshness: refuse to approve on stale data.
        stale_minutes = Settings.swm_get_int("device_offline_minutes", 120)
        stale_limit = fields.Datetime.subtract(now, minutes=stale_minutes)
        if not self.last_reading_time or self.last_reading_time < stale_limit:
            return {"ok": False, "reason": "stale",
                    "message": _("No recent sensor reading. Close the lid, "
                                 "wait for the sensor to report, and try "
                                 "again.")}

        # The core rule: approve only if the bin is actually empty.
        if self.fill_percentage > t["empty"]:
            return {"ok": False, "reason": "not_empty",
                    "message": _("Sensor still reports %s%% fill — above "
                                 "the empty threshold of %s%%. The bin is "
                                 "not empty yet. Close the lid and wait "
                                 "for a fresh reading if you just emptied "
                                 "it.") % (round(self.fill_percentage),
                                           int(t["empty"]))}

        request = self.open_request_id
        if request:
            request.sudo().action_mark_done(
                qr_confirmed=True,
                note=_("Approved via staff QR scan by %s",
                       self.env.user.name))
        self.sudo().write({
            "status": "available",
            "last_status_change": now,
            "last_emptied_time": now,
            "collection_completed_time": now,
            "full_since": False,
        })
        self.sudo().message_post(body=_(
            "Collection approved via staff QR scan by %s "
            "(sensor fill: %s%%).",
            self.env.user.name, round(self.fill_percentage)))
        if request:
            self.env["otm.swm.notification.rule"].sudo().process_event(
                "collection_completed", self, request=request)
        return {"ok": True, "reason": "approved",
                "message": _("Collection approved — bin is now marked "
                             "Available.")}

    # ------------------------------------------------------------------
    # Crons
    # ------------------------------------------------------------------
    @api.model
    def cron_check_device_offline(self):
        minutes = self.env["res.config.settings"].swm_get_int(
            "device_offline_minutes", 120)
        limit = fields.Datetime.subtract(
            fields.Datetime.now(), minutes=minutes)
        stale = self.search([
            ("active", "=", True),
            ("device_online", "=", True),
            ("last_communication", "<", limit),
        ])
        for rec in stale:
            rec.write({"device_online": False})
            if rec.status not in FULL_LIKE:
                rec._change_status("offline")
            self.env["otm.swm.notification.rule"].sudo().process_event(
                "device_offline", rec)

    @api.model
    def cron_purge_old_readings(self):
        days = self.env["res.config.settings"].swm_get_int(
            "reading_retention_days", 90)
        if days <= 0:
            return
        limit = fields.Datetime.subtract(fields.Datetime.now(), days=days)
        old = self.env["otm.swm.sensor.reading"].search(
            [("create_date", "<", limit)])
        old.unlink()
