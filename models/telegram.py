# Part of Otomater. See LICENSE file for full copyright and licensing details.
import logging
import secrets

import requests

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
TIMEOUT = 10


class SwmTelegram(models.AbstractModel):
    """Thin Telegram Bot API transport. Failures never raise into the
    calling (sensor) transaction — they are returned as (False, detail)."""
    _name = "otm.swm.telegram"
    _description = "Telegram Transport Helper"

    @api.model
    def _bot_token(self):
        return self.env["res.config.settings"].swm_get_str(
            "telegram_bot_token")

    @api.model
    def send_message(self, chat_id, text):
        token = self._bot_token()
        if not token:
            return False, "Bot token not configured"
        if not chat_id:
            return False, "Empty chat id"
        try:
            resp = requests.post(
                TELEGRAM_API.format(token=token, method="sendMessage"),
                json={"chat_id": chat_id, "text": text,
                      "disable_web_page_preview": True},
                timeout=TIMEOUT,
            )
            body = resp.text[:500]
            if resp.ok and resp.json().get("ok"):
                return True, body
            return False, body
        except Exception as exc:  # noqa: BLE001 - transport must not raise
            _logger.warning("SWM Telegram send failed: %s", exc)
            return False, str(exc)

    @api.model
    def set_webhook(self):
        """Convenience helper for administrators: registers the webhook
        URL (base_url + secret path) with Telegram."""
        Settings = self.env["res.config.settings"]
        token = self._bot_token()
        secret = Settings.swm_get_str("telegram_webhook_secret")
        base = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        if not (token and secret and base):
            return False, "Configure bot token and webhook secret first"
        url = f"{base}/smart_waste/telegram/webhook/{secret}"
        try:
            resp = requests.post(
                TELEGRAM_API.format(token=token, method="setWebhook"),
                json={"url": url}, timeout=TIMEOUT)
            return resp.ok, resp.text[:500]
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)


class SwmTelegramToken(models.Model):
    _name = "otm.swm.telegram.token"
    _description = "Telegram Registration Token"
    _order = "id desc"

    token = fields.Char(required=True, index=True, readonly=True, copy=False)
    member_id = fields.Many2one(
        "otm.swm.association.member", required=True, ondelete="cascade",
        string="Association Member")
    expires_at = fields.Datetime(required=True, readonly=True)
    used = fields.Boolean(readonly=True)
    used_at = fields.Datetime(readonly=True)

    _sql_constraints = [
        ("token_uniq", "unique(token)", "Token must be unique."),
    ]

    @api.model
    def issue_for_member(self, member):
        """Invalidate previous pending tokens and issue a fresh single-use
        token. Never exposes internal record IDs in the deep link."""
        hours = self.env["res.config.settings"].swm_get_int(
            "telegram_token_expiry_hours", 24)
        self.sudo().search([
            ("member_id", "=", member.id), ("used", "=", False),
        ]).unlink()
        return self.sudo().create({
            "token": secrets.token_urlsafe(24),
            "member_id": member.id,
            "expires_at": fields.Datetime.add(
                fields.Datetime.now(), hours=hours),
        })

    def deep_link(self):
        self.ensure_one()
        username = self.env["res.config.settings"].swm_get_str(
            "telegram_bot_username")
        if not username:
            return ""
        return f"https://t.me/{username}?start={self.token}"

    @api.model
    def consume(self, token_value, chat_id, tg_user_id=None, username=None):
        """Validate + consume a token coming from the webhook /start.
        Returns the linked member record or empty recordset."""
        Member = self.env["otm.swm.association.member"]
        rec = self.sudo().search([("token", "=", token_value)], limit=1)
        if not rec or rec.used:
            return Member.browse()
        if rec.expires_at < fields.Datetime.now():
            return Member.browse()
        now = fields.Datetime.now()
        rec.write({"used": True, "used_at": now})
        rec.member_id.sudo().write({
            "telegram_connected": True,
            "telegram_chat_id": str(chat_id),
            "telegram_user_id": str(tg_user_id or ""),
            "telegram_username": username or "",
            "telegram_connected_on": now,
        })
        return rec.member_id

    @api.model
    def cron_purge_expired(self):
        self.sudo().search([
            ("used", "=", False),
            ("expires_at", "<", fields.Datetime.now()),
        ]).unlink()
