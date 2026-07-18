# Part of Otomater. See LICENSE file for full copyright and licensing details.
from odoo import fields
from odoo.tests import tagged

from .common import SwmCommon


@tagged("post_install", "-at_install", "swm")
class TestTelegramToken(SwmCommon):

    def setUp(self):
        super().setUp()
        self.member = self.env["otm.swm.association.member"].create({
            "name": "Token Member",
            "association_id": self.assoc.id,
            "street_id": self.street.id,
        })
        self.Token = self.env["otm.swm.telegram.token"]
        self.set_param("telegram_bot_username", "swm_test_bot")

    def test_deep_link_has_no_internal_ids(self):
        token = self.Token.issue_for_member(self.member)
        link = token.deep_link()
        self.assertIn("t.me/swm_test_bot?start=", link)
        self.assertNotIn(str(self.member.id), link.rsplit("=", 1)[1],
                         "Deep link payload must not embed record IDs")

    def test_consume_links_member(self):
        token = self.Token.issue_for_member(self.member)
        member = self.Token.consume(
            token.token, chat_id="12345", tg_user_id="999",
            username="anita_tg")
        self.assertEqual(member, self.member)
        self.assertTrue(self.member.telegram_connected)
        self.assertEqual(self.member.sudo().telegram_chat_id, "12345")

    def test_token_single_use(self):
        token = self.Token.issue_for_member(self.member)
        self.Token.consume(token.token, chat_id="111")
        second = self.Token.consume(token.token, chat_id="222")
        self.assertFalse(second, "A consumed token must be rejected")
        self.assertEqual(self.member.sudo().telegram_chat_id, "111",
                         "Second attempt must not overwrite the link")

    def test_token_expiry(self):
        token = self.Token.issue_for_member(self.member)
        token.sudo().write({"expires_at": fields.Datetime.subtract(
            fields.Datetime.now(), hours=1)})
        member = self.Token.consume(token.token, chat_id="333")
        self.assertFalse(member, "Expired token must be rejected")
        self.assertFalse(self.member.telegram_connected)

    def test_reissue_invalidates_previous(self):
        first = self.Token.issue_for_member(self.member)
        first_value = first.token
        self.Token.issue_for_member(self.member)
        member = self.Token.consume(first_value, chat_id="444")
        self.assertFalse(member,
                         "Older pending token is invalidated on re-issue")

    def test_unknown_token_rejected(self):
        member = self.Token.consume("does-not-exist", chat_id="555")
        self.assertFalse(member)

    def test_purge_cron(self):
        token = self.Token.issue_for_member(self.member)
        token.sudo().write({"expires_at": fields.Datetime.subtract(
            fields.Datetime.now(), hours=2)})
        self.Token.cron_purge_expired()
        self.assertFalse(token.exists())

    def test_disconnect(self):
        token = self.Token.issue_for_member(self.member)
        self.Token.consume(token.token, chat_id="666")
        self.member.action_disconnect_telegram()
        self.assertFalse(self.member.telegram_connected)
        self.assertFalse(self.member.sudo().telegram_chat_id)
