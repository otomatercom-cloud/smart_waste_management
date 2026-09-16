# Part of Otomater. See LICENSE file for full copyright and licensing details.
from odoo import fields
from odoo.tests import tagged

from .common import SwmCommon


@tagged("post_install", "-at_install", "swm")
class TestStaffQrConfirm(SwmCommon):

    def _fill(self, pct):
        self.set_param("dedupe_minutes", "0")
        self.bin.process_reading(fill_percentage=pct)

    def test_approve_when_actually_empty(self):
        self._fill(97)
        req = self.env["otm.swm.collection.request"].search(
            [("bin_id", "=", self.bin.id)])
        self._fill(96)  # still full-like, keeps request open
        # Staff empties the bin; sensor reports empty:
        self.bin.write({"fill_percentage": 10,
                        "last_reading_time": fields.Datetime.now()})
        result = self.bin.with_user(
            self.staff_user).sudo().qr_confirm_collection()
        self.assertTrue(result["ok"])
        self.assertEqual(self.bin.status, "available")
        self.assertEqual(req.state, "done")
        self.assertTrue(req.qr_confirmed)
        self.assertFalse(req.manual_completion)
        self.assertFalse(req.sensor_confirmed)

    def test_reject_when_not_empty(self):
        self._fill(97)
        req = self.env["otm.swm.collection.request"].search(
            [("bin_id", "=", self.bin.id)])
        result = self.bin.with_user(
            self.staff_user).sudo().qr_confirm_collection()
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "not_empty")
        self.assertEqual(req.state, "assigned",
                         "Request must stay open when sensor is not empty")
        self.assertNotEqual(self.bin.status, "available")

    def test_reject_on_stale_reading(self):
        self._fill(97)
        self.bin.write({
            "fill_percentage": 5,
            "last_reading_time": fields.Datetime.subtract(
                fields.Datetime.now(), minutes=999),
        })
        result = self.bin.with_user(
            self.staff_user).sudo().qr_confirm_collection()
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "stale")

    def test_reject_under_maintenance(self):
        self.bin.action_set_maintenance()
        self.bin.write({"fill_percentage": 5,
                        "last_reading_time": fields.Datetime.now()})
        result = self.bin.qr_confirm_collection()
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "maintenance")

    def test_approve_without_open_request(self):
        """Bin readable-empty with no pending request: approval still
        refreshes status to available without crashing."""
        self.bin.write({"fill_percentage": 8,
                        "last_reading_time": fields.Datetime.now()})
        result = self.bin.qr_confirm_collection()
        self.assertTrue(result["ok"])
        self.assertEqual(self.bin.status, "available")


@tagged("post_install", "-at_install", "swm")
class TestRfidAutoConfirmCollection(SwmCommon):
    """A staff/supervisor RFID tap that closes on a full bin should
    attempt the same sensor-gated approval as the QR flow - and must
    be just as fraud-proof: tapping alone, without the sensor
    genuinely reading empty, must never mark the bin Available."""

    def setUp(self):
        super().setUp()
        self.staff_card = self.env["otm.swm.rfid.card"].create({
            "card_uid": "AUTO-CONFIRM-STAFF",
            "holder_type": "staff",
            "staff_id": self.staff.id,
        })
        self.set_param("rfid_enabled", "True")
        self.set_param("dedupe_minutes", "0")
        self.set_param("auto_confirm_collection_via_rfid", "True")
        self.bin.process_reading(fill_percentage=97)  # bin now full-like

    def test_staff_tap_auto_approves_when_genuinely_empty(self):
        # Staff tapped in, physically emptied it, and a fresh sensor
        # reading (simulated here) confirms it before close fires.
        self.bin.check_rfid_access("AUTO-CONFIRM-STAFF")
        self.bin.write({"fill_percentage": 5,
                        "last_reading_time": fields.Datetime.now()})
        result = self.bin.close_rfid_session()
        self.assertTrue(result.get("collection_confirmed"))
        self.assertEqual(self.bin.status, "available")

    def test_staff_tap_does_not_auto_approve_when_still_full(self):
        # The core anti-manipulation guarantee: tapping the card is
        # not itself proof of emptying - the sensor still has to
        # agree, exactly like the QR flow.
        self.bin.check_rfid_access("AUTO-CONFIRM-STAFF")
        # No fresh empty reading arrives - fill% stays at 97.
        result = self.bin.close_rfid_session()
        self.assertFalse(result.get("collection_confirmed"))
        self.assertNotEqual(self.bin.status, "available")

    def test_member_tap_never_triggers_auto_confirm(self):
        member = self.env["otm.swm.association.member"].create({
            "name": "Auto Confirm Member Test",
            "association_id": self.assoc.id,
            "street_id": self.street.id,
        })
        member_card = self.env["otm.swm.rfid.card"].create({
            "card_uid": "AUTO-CONFIRM-MEMBER",
            "holder_type": "member",
            "member_id": member.id,
        })
        self.set_param("lock_when_full_enabled", "False")
        self.bin.check_rfid_access("AUTO-CONFIRM-MEMBER")
        self.bin.write({"fill_percentage": 5,
                        "last_reading_time": fields.Datetime.now()})
        result = self.bin.close_rfid_session()
        self.assertNotIn("collection_confirmed", result)
        self.assertNotEqual(self.bin.status, "available")

    def test_setting_off_disables_auto_confirm(self):
        self.set_param("auto_confirm_collection_via_rfid", "False")
        self.bin.check_rfid_access("AUTO-CONFIRM-STAFF")
        self.bin.write({"fill_percentage": 5,
                        "last_reading_time": fields.Datetime.now()})
        result = self.bin.close_rfid_session()
        self.assertNotIn("collection_confirmed", result)
        self.assertNotEqual(self.bin.status, "available")

    def test_staff_tap_on_non_full_bin_does_not_attempt_confirm(self):
        self.bin.process_reading(fill_percentage=10)  # back to available
        self.bin.check_rfid_access("AUTO-CONFIRM-STAFF")
        result = self.bin.close_rfid_session()
        self.assertNotIn("collection_confirmed", result)
