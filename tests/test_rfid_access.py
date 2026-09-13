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


@tagged("post_install", "-at_install", "swm")
class TestRfidLockWhenFull(SwmCommon):

    def setUp(self):
        super().setUp()
        self.member = self.env["otm.swm.association.member"].create({
            "name": "Lockout Test Member",
            "association_id": self.assoc.id,
            "street_id": self.street.id,
        })
        self.member_card = self.env["otm.swm.rfid.card"].create({
            "card_uid": "MEMBER-CARD-1",
            "holder_type": "member",
            "member_id": self.member.id,
        })
        self.staff_card = self.env["otm.swm.rfid.card"].create({
            "card_uid": "STAFF-CARD-1",
            "holder_type": "staff",
            "staff_id": self.staff.id,
        })
        self.set_param("rfid_enabled", "True")
        self.set_param("status_confirm_count", "1")

    def _make_full(self):
        self.bin.process_reading(fill_percentage=97)
        self.assertEqual(self.bin.status, "collection_pending")

    def test_member_denied_when_bin_full_and_lock_enabled(self):
        self.set_param("lock_when_full_enabled", "True")
        self._make_full()
        result = self.bin.check_rfid_access("MEMBER-CARD-1")
        self.assertEqual(result["access"], "denied")
        self.assertEqual(result["reason"], "bin_full_staff_only")

    def test_staff_always_granted_even_when_full(self):
        self.set_param("lock_when_full_enabled", "True")
        self._make_full()
        result = self.bin.check_rfid_access("STAFF-CARD-1")
        self.assertEqual(result["access"], "granted")
        self.assertEqual(self.bin.last_access_staff_id, self.staff)
        self.assertFalse(self.bin.last_access_member_id)

    def test_member_granted_when_bin_not_full(self):
        result = self.bin.check_rfid_access("MEMBER-CARD-1")
        self.assertEqual(result["access"], "granted")
        self.assertEqual(self.bin.last_access_member_id, self.member)

    def test_member_allowed_on_full_bin_when_toggle_off(self):
        self.set_param("lock_when_full_enabled", "False")
        self._make_full()
        result = self.bin.check_rfid_access("MEMBER-CARD-1")
        self.assertEqual(result["access"], "granted")

    def test_staff_card_bypasses_subscription_check(self):
        self.set_param("subscription_enforcement_enabled", "True")
        self.staff_card.staff_id  # sanity: card resolved to staff
        # Staff cards have no subscription concept at all - confirm a
        # staff card opens even with the strictest enforcement on and
        # no subscription fields ever touched.
        result = self.bin.check_rfid_access("STAFF-CARD-1")
        self.assertEqual(result["access"], "granted")

    def test_log_records_staff_id_and_holder_name(self):
        self._make_full()
        self.bin.check_rfid_access("STAFF-CARD-1")
        log = self.env["otm.swm.bin.access.log"].search(
            [("card_uid", "=", "STAFF-CARD-1")], limit=1)
        self.assertEqual(log.staff_id, self.staff)
        self.assertFalse(log.member_id)
        self.assertEqual(log.holder_name, self.staff.name)
        self.assertTrue(log.granted)

    def test_card_requires_exactly_one_holder(self):
        with self.assertRaises(Exception):
            self.env["otm.swm.rfid.card"].create({
                "card_uid": "BAD-CARD-1",
                "holder_type": "member",
                # no member_id set - should raise
            })
        with self.assertRaises(Exception):
            self.env["otm.swm.rfid.card"].create({
                "card_uid": "BAD-CARD-2",
                "holder_type": "member",
                "member_id": self.member.id,
                "staff_id": self.staff.id,  # both set - should raise
            })


@tagged("post_install", "-at_install", "swm")
class TestRfidWeightSession(SwmCommon):
    """A visit can drop several bags before the lock re-closes - the
    total the person actually put in is end-of-session weight minus
    start-of-session weight, not any single instant reading."""

    def setUp(self):
        super().setUp()
        self.member = self.env["otm.swm.association.member"].create({
            "name": "Session Test Member",
            "association_id": self.assoc.id,
            "street_id": self.street.id,
        })
        self.card = self.env["otm.swm.rfid.card"].create({
            "card_uid": "SESSION-CARD-1",
            "holder_type": "member",
            "member_id": self.member.id,
        })
        self.set_param("rfid_enabled", "True")
        self.set_param("weight_capture_enabled", "True")
        self.set_param("session_window_seconds", "30")

    def test_single_bag_session(self):
        # Bin starts empty (0 kg on the scale), one bag added at open.
        self.bin.check_rfid_access("SESSION-CARD-1", weight_kg=2.0)
        log = self.env["otm.swm.bin.access.log"].search(
            [("card_uid", "=", "SESSION-CARD-1")], limit=1)
        self.assertEqual(log.session_start_weight_kg, 2.0)
        self.assertFalse(log.session_closed)
        # Window hasn't elapsed yet - not finalised.
        self.assertEqual(log.weight_deposited_kg, 0.0)

    def test_two_bags_same_visit_sum_correctly(self):
        self.bin.check_rfid_access("SESSION-CARD-1", weight_kg=2.0)
        # A follow-up status ping mid-visit, after a second bag lands -
        # the scale now reads the running total, 3.0 kg.
        self.bin.process_reading(fill_percentage=10, weight_kg=3.0)
        log = self.env["otm.swm.bin.access.log"].search(
            [("card_uid", "=", "SESSION-CARD-1")], limit=1)
        self.assertEqual(log.session_end_weight_kg, 3.0)
        # Force the window closed to check the finalised total.
        log.bin_id.write({"session_deadline": fields.Datetime.subtract(
            fields.Datetime.now(), minutes=1)})
        log.bin_id._close_stale_session()
        self.assertTrue(log.session_closed)
        self.assertEqual(log.weight_deposited_kg, 1.0)

    def test_session_closes_lazily_on_next_tap(self):
        self.bin.check_rfid_access("SESSION-CARD-1", weight_kg=2.0)
        first_log = self.env["otm.swm.bin.access.log"].search(
            [("card_uid", "=", "SESSION-CARD-1")], limit=1)
        self.bin.write({"session_deadline": fields.Datetime.subtract(
            fields.Datetime.now(), minutes=1)})
        # A second, unrelated tap should close the first session before
        # processing itself - no need to wait for the cron.
        self.bin.check_rfid_access("SESSION-CARD-1", weight_kg=2.5)
        self.assertTrue(first_log.session_closed)

    def test_denied_tap_never_opens_a_session(self):
        self.bin.card = self.card  # noqa - readability marker only
        self.member.write({"subscription_active": False})
        self.set_param("subscription_enforcement_enabled", "True")
        self.bin.check_rfid_access("SESSION-CARD-1", weight_kg=2.0)
        self.assertFalse(self.bin.active_session_log_id)
        log = self.env["otm.swm.bin.access.log"].search(
            [("card_uid", "=", "SESSION-CARD-1")], limit=1)
        self.assertTrue(log.session_closed)
        self.assertFalse(log.granted)

    def test_cron_closes_stale_sessions(self):
        self.bin.check_rfid_access("SESSION-CARD-1", weight_kg=2.0)
        self.bin.process_reading(fill_percentage=10, weight_kg=5.0)
        self.bin.write({"session_deadline": fields.Datetime.subtract(
            fields.Datetime.now(), minutes=1)})
        self.env["otm.swm.bin"].cron_close_stale_rfid_sessions()
        log = self.env["otm.swm.bin.access.log"].search(
            [("card_uid", "=", "SESSION-CARD-1")], limit=1)
        self.assertTrue(log.session_closed)
        self.assertEqual(log.weight_deposited_kg, 3.0)
        self.assertFalse(self.bin.active_session_log_id)

    def test_weight_never_goes_negative(self):
        # If the reading somehow dips below the start (sensor noise),
        # deposited must clamp to 0, never a negative "removed" figure.
        self.bin.check_rfid_access("SESSION-CARD-1", weight_kg=5.0)
        self.bin.process_reading(fill_percentage=10, weight_kg=4.8)
        self.bin.write({"session_deadline": fields.Datetime.subtract(
            fields.Datetime.now(), minutes=1)})
        self.bin._close_stale_session()
        log = self.env["otm.swm.bin.access.log"].search(
            [("card_uid", "=", "SESSION-CARD-1")], limit=1)
        self.assertEqual(log.weight_deposited_kg, 0.0)
