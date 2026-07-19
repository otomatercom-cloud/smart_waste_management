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
