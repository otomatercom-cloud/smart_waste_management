# Part of Otomater. See LICENSE file for full copyright and licensing details.
from odoo import api, fields, models

PARAM_PREFIX = "smart_waste_management."


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    swm_threshold_nearly_full = fields.Integer(
        string="Nearly Full Threshold (%)", default=80,
        config_parameter=PARAM_PREFIX + "threshold_nearly_full")
    swm_threshold_full = fields.Integer(
        string="Full Threshold (%)", default=95,
        config_parameter=PARAM_PREFIX + "threshold_full")
    swm_threshold_empty = fields.Integer(
        string="Empty Detection Threshold (%)", default=25,
        config_parameter=PARAM_PREFIX + "threshold_empty")
    swm_hysteresis = fields.Integer(
        string="Hysteresis Margin (%)", default=3,
        config_parameter=PARAM_PREFIX + "hysteresis",
        help="A status only changes back once the fill level moves this many "
             "percent past the threshold, preventing sensor flutter such as "
             "94→96→94→96 generating repeated notifications.")
    swm_dedupe_minutes = fields.Integer(
        string="Duplicate Reading Window (minutes)", default=10,
        config_parameter=PARAM_PREFIX + "dedupe_minutes",
        help="Identical consecutive readings inside this window are not "
             "stored as new history rows (last-communication time is still "
             "updated).")
    swm_min_storage_seconds = fields.Integer(
        string="Min Seconds Between Stored Readings", default=60,
        config_parameter=PARAM_PREFIX + "min_storage_seconds",
        help="At most one reading row is stored per bin within this "
             "interval, unless the fill changes significantly. The live "
             "status engine still processes every reading. 0 disables "
             "throttling.")
    swm_storage_delta = fields.Integer(
        string="Significant Fill Change (%)", default=5,
        config_parameter=PARAM_PREFIX + "storage_delta",
        help="A fill change of at least this many percent is stored "
             "immediately, bypassing the storage throttle.")
    swm_status_confirm_count = fields.Integer(
        string="Status Confirmation Readings", default=2,
        config_parameter=PARAM_PREFIX + "status_confirm_count",
        help="Consecutive agreeing readings required before a bin enters "
             "Full or Collected. Protects against ultrasonic noise firing "
             "false requests, completions, and Telegram alerts. 1 "
             "disables; 2-3 recommended for HC-SR04 sensors.")

    # ---- RFID lock / subscription / weight capture ----
    swm_rfid_enabled = fields.Boolean(
        string="RFID Access Control", default=False,
        config_parameter=PARAM_PREFIX + "rfid_enabled",
        help="When off, every bin's RFID lock (if installed) opens for "
             "any tap with no checks and nothing is logged - the bin "
             "behaves as if no lock were installed at all. Turn on once "
             "cards have been issued under Structure > RFID Cards.")
    swm_lock_when_full_enabled = fields.Boolean(
        string="Lock Full Bins to Staff Only", default=True,
        config_parameter=PARAM_PREFIX + "lock_when_full_enabled",
        help="Only applies when RFID Access Control is on. When on, a "
             "member's card is denied while the bin is Full / Collection "
             "Pending / Collection In Progress - only a staff or "
             "supervisor card opens it in that state, so a collector "
             "can service and empty it. When off, a valid member card "
             "always opens the bin regardless of fill status.")
    swm_subscription_enforcement_enabled = fields.Boolean(
        string="Enforce Subscription on Access", default=True,
        config_parameter=PARAM_PREFIX + "subscription_enforcement_enabled",
        help="Only takes effect when RFID Access Control is on. When on, "
             "a registered card whose member's subscription has lapsed "
             "is denied. When off, any active registered card opens the "
             "bin regardless of subscription status (still logged).")
    swm_subscription_renewal_days = fields.Integer(
        string="Subscription Renewal Period (days)", default=30,
        config_parameter=PARAM_PREFIX + "subscription_renewal_days",
        help="How far the 'Renew Subscription' button on a member "
             "extends their expiry date, counted from today.")
    swm_weight_capture_enabled = fields.Boolean(
        string="Weight Capture", default=False,
        config_parameter=PARAM_PREFIX + "weight_capture_enabled",
        help="When on, a weight_kg value sent with an RFID tap is "
             "stored on the bin's live status and on the access log "
             "row. Independent of RFID Access Control - a bin can "
             "report weight without having a lock, or vice versa.")
    swm_heavy_weight_threshold_kg = fields.Float(
        string="Heavy Dump Threshold (kg)", default=10.0,
        config_parameter=PARAM_PREFIX + "heavy_weight_threshold_kg",
        help="An access tap reporting at or above this weight is "
             "flagged as a heavy dump on the dashboard - useful for "
             "spotting bulk/commercial waste going into a household "
             "bin, or a single large deposit worth a manual check.")
    swm_subscription_reminder_days_before = fields.Integer(
        string="Subscription Reminder (days before expiry)", default=5,
        config_parameter=PARAM_PREFIX + "subscription_reminder_days_before",
        help="A monthly cron sends a Telegram reminder to any connected "
             "member whose subscription expires within this many days, "
             "and to any member whose subscription has already lapsed.")
    swm_underpayment_alerts_enabled = fields.Boolean(
        string="Underpayment Alerts", default=True,
        config_parameter=PARAM_PREFIX + "underpayment_alerts_enabled",
        help="When on, a member is sent a Telegram notice the moment a "
             "recorded payment is less than their plan's price at the "
             "time - e.g. a partial or discounted amount entered by "
             "hand under Subscription Payments. Renewals made through "
             "the Renew Subscription button always charge the full "
             "price and never trigger this.")

    swm_reading_retention_days = fields.Integer(
        string="Sensor Reading Retention (days)", default=90,
        config_parameter=PARAM_PREFIX + "reading_retention_days")
    swm_device_offline_minutes = fields.Integer(
        string="Device Offline After (minutes)", default=120,
        config_parameter=PARAM_PREFIX + "device_offline_minutes")
    swm_telegram_bot_token = fields.Char(
        string="Telegram Bot Token",
        config_parameter=PARAM_PREFIX + "telegram_bot_token")
    swm_telegram_bot_username = fields.Char(
        string="Telegram Bot Username",
        config_parameter=PARAM_PREFIX + "telegram_bot_username",
        help="Without @, e.g. OtomaterWasteBot. Used to build "
             "t.me deep links for QR registration.")
    swm_telegram_webhook_secret = fields.Char(
        string="Telegram Webhook Secret",
        config_parameter=PARAM_PREFIX + "telegram_webhook_secret",
        help="Random path segment protecting the webhook endpoint.")
    swm_telegram_default_group = fields.Char(
        string="Default Telegram Group Chat ID",
        config_parameter=PARAM_PREFIX + "telegram_default_group")
    swm_telegram_token_expiry_hours = fields.Integer(
        string="Registration Token Expiry (hours)", default=24,
        config_parameter=PARAM_PREFIX + "telegram_token_expiry_hours")
    swm_public_complaints_enabled = fields.Boolean(
        string="Allow Public Complaints from Bin QR Page", default=True,
        config_parameter=PARAM_PREFIX + "public_complaints_enabled")
    swm_public_show_fill_percent = fields.Boolean(
        string="Show Exact Fill % on Public Page", default=True,
        config_parameter=PARAM_PREFIX + "public_show_fill_percent")

    @api.model
    def swm_get_int(self, key, default):
        icp = self.env["ir.config_parameter"].sudo()
        try:
            return int(icp.get_param(PARAM_PREFIX + key, default))
        except (TypeError, ValueError):
            return default

    @api.model
    def swm_get_str(self, key, default=""):
        icp = self.env["ir.config_parameter"].sudo()
        return (icp.get_param(PARAM_PREFIX + key, default) or default).strip()

    @api.model
    def swm_get_bool(self, key, default=True):
        icp = self.env["ir.config_parameter"].sudo()
        val = icp.get_param(PARAM_PREFIX + key)
        if val is None:
            return default
        return str(val).lower() not in ("false", "0", "")
