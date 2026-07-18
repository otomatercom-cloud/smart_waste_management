# Part of Otomater. See LICENSE file for full copyright and licensing details.
import hmac
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class SwmTelegramWebhook(http.Controller):

    @http.route("/smart_waste/telegram/webhook/<string:secret>",
                type="http", auth="none", methods=["POST"], csrf=False,
                save_session=False)
    def webhook(self, secret, **kwargs):
        env = request.env(su=True)
        expected = env["res.config.settings"].swm_get_str(
            "telegram_webhook_secret")
        if not expected or not hmac.compare_digest(expected, secret or ""):
            return request.make_response("forbidden", status=403)
        try:
            update = json.loads(
                request.httprequest.get_data(as_text=True) or "{}")
        except (ValueError, TypeError):
            return request.make_response("bad request", status=400)

        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        text = (message.get("text") or "").strip()
        chat_id = chat.get("id")

        reply = None
        if text.startswith("/start") and chat_id:
            parts = text.split(maxsplit=1)
            token_value = parts[1].strip() if len(parts) > 1 else ""
            if token_value:
                member = env["otm.swm.telegram.token"].consume(
                    token_value, chat_id,
                    tg_user_id=sender.get("id"),
                    username=sender.get("username"))
                if member:
                    reply = (
                        f"✅ Telegram connected for {member.name} "
                        f"({member.association_id.name}). You will now "
                        "receive waste collection notifications according "
                        "to your preferences.")
                else:
                    reply = ("⚠️ This registration link is invalid, expired "
                             "or already used. Please generate a new QR "
                             "code from the portal and try again.")
            else:
                reply = ("👋 Welcome! To connect your account, scan the "
                         "'Connect Telegram' QR code from your association "
                         "portal page.")
        if reply and chat_id:
            env["otm.swm.telegram"].send_message(chat_id, reply)
        # Always 200 so Telegram does not retry forever.
        return request.make_response("ok", status=200)
