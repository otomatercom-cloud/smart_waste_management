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
