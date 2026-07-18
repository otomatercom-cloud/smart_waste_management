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
                        signal_strength=None, raw=None):
        self.ensure_one()
        now = fields.Datetime.now()
        Settings = self.env["res.config.settings"]

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

        # Duplicate suppression: same values inside the dedupe window only
        # refresh the communication timestamp.
        dedupe_min = Settings.swm_get_int("dedupe_minutes", 10)
        last = self.env["otm.swm.sensor.reading"].search(
            [("bin_id", "=", self.id)], order="id desc", limit=1)
        duplicate = bool(
            last and dedupe_min > 0
            and abs((last.fill_percentage or 0) - fill_percentage) < 0.5
            and (distance_cm is None
                 or abs((last.distance_cm or 0) - distance_cm) < 0.5)
            and last.create_date
            and (now - last.create_date).total_seconds() < dedupe_min * 60)

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
            return {"changed": False}
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
