# Part of Otomater. See LICENSE file for full copyright and licensing details.
from odoo import fields
from odoo.tests import tagged

from .common import SwmCommon


@tagged("post_install", "-at_install", "swm")
class TestRfidAccess(SwmCommon):

    def setUp(self):
        super().setUp()
        self.member = self.env["otm.swm.association.member"].create({
            "name": "RFID Test Member",
            "association_id": self.assoc.id,
            "street_id": self.street.id,
        })
        self.card = self.env["otm.swm.rfid.card"].create({
            "card_uid": "AA:BB:CC:DD",
            "member_id": self.member.id,
        })

    def test_disabled_feature_always_grants_no_log(self):
        self.set_param("rfid_enabled", "False")
        Log = self.env["otm.swm.bin.access.log"]
        before = Log.search_count([("bin_id", "=", self.bin.id)])
        result = self.bin.check_rfid_access("AA:BB:CC:DD")
        self.assertEqual(result["access"], "granted")
        self.assertEqual(result["reason"], "rfid_feature_disabled")
        after = Log.search_count([("bin_id", "=", self.bin.id)])
        self.assertEqual(before, after, "Disabled feature must not log")

    def test_valid_card_valid_subscription_grants(self):
        self.set_param("rfid_enabled", "True")
        result = self.bin.check_rfid_access("AA:BB:CC:DD")
        self.assertEqual(result["access"], "granted")
        self.assertEqual(self.bin.last_access_member_id, self.member)
        log = self.env["otm.swm.bin.access.log"].search(
            [("bin_id", "=", self.bin.id)], limit=1)
        self.assertTrue(log.granted)
        self.assertEqual(log.member_id, self.member)

    def test_unknown_card_denied(self):
        self.set_param("rfid_enabled", "True")
        result = self.bin.check_rfid_access("00:00:00:00")
        self.assertEqual(result["access"], "denied")
        self.assertEqual(result["reason"], "card_unknown")
        log = self.env["otm.swm.bin.access.log"].search(
            [("bin_id", "=", self.bin.id), ("card_uid", "=", "00:00:00:00")])
        self.assertFalse(log.granted)
        self.assertFalse(log.member_id)

    def test_inactive_card_denied(self):
        self.set_param("rfid_enabled", "True")
        self.card.active = False
        result = self.bin.check_rfid_access("AA:BB:CC:DD")
        self.assertEqual(result["access"], "denied")
        self.assertEqual(result["reason"], "card_inactive")

    def test_expired_subscription_denied_when_enforced(self):
        self.set_param("rfid_enabled", "True")
        self.set_param("subscription_enforcement_enabled", "True")
        self.member.write({
            "subscription_expiry": fields.Date.subtract(
                fields.Date.today(), days=1),
        })
        result = self.bin.check_rfid_access("AA:BB:CC:DD")
        self.assertEqual(result["access"], "denied")
        self.assertEqual(result["reason"], "subscription_expired")

    def test_expired_subscription_allowed_when_not_enforced(self):
        self.set_param("rfid_enabled", "True")
        self.set_param("subscription_enforcement_enabled", "False")
        self.member.write({
            "subscription_expiry": fields.Date.subtract(
                fields.Date.today(), days=1),
        })
        result = self.bin.check_rfid_access("AA:BB:CC:DD")
        self.assertEqual(result["access"], "granted")

    def test_subscription_inactive_flag_denies_regardless_of_expiry(self):
        self.set_param("rfid_enabled", "True")
        self.member.write({
            "subscription_active": False,
            "subscription_expiry": fields.Date.add(
                fields.Date.today(), days=30),
        })
        result = self.bin.check_rfid_access("AA:BB:CC:DD")
        self.assertEqual(result["access"], "denied")

    def test_renew_subscription_extends_expiry(self):
        self.member.write({"subscription_active": False,
                           "subscription_expiry": fields.Date.subtract(
                               fields.Date.today(), days=5)})
        self.member.action_renew_subscription()
        self.assertTrue(self.member.subscription_active)
        self.assertGreater(self.member.subscription_expiry,
                           fields.Date.today())
        self.assertTrue(self.member.subscription_valid)

    def test_weight_capture_independent_of_rfid(self):
        self.set_param("rfid_enabled", "False")
        self.set_param("weight_capture_enabled", "True")
        self.bin.check_rfid_access("anything", weight_kg=12.5)
        self.assertEqual(self.bin.current_weight_kg, 12.5)

    def test_weight_ignored_when_capture_disabled(self):
        self.set_param("rfid_enabled", "False")
        self.set_param("weight_capture_enabled", "False")
        self.bin.check_rfid_access("anything", weight_kg=12.5)
        self.assertEqual(self.bin.current_weight_kg, 0.0)

    def test_weight_logged_on_granted_tap(self):
        self.set_param("rfid_enabled", "True")
        self.set_param("weight_capture_enabled", "True")
        self.bin.check_rfid_access("AA:BB:CC:DD", weight_kg=8.0)
        log = self.env["otm.swm.bin.access.log"].search(
            [("bin_id", "=", self.bin.id)], limit=1)
        self.assertEqual(log.weight_kg, 8.0)

    def test_duplicate_card_uid_rejected(self):
        with self.assertRaises(Exception):
            self.env["otm.swm.rfid.card"].create({
                "card_uid": "AA:BB:CC:DD",  # already used by self.card
                "member_id": self.member.id,
            })
