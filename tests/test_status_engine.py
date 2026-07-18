# Part of Otomater. See LICENSE file for full copyright and licensing details.
from odoo import fields
from odoo.tests import tagged

from .common import SwmCommon


@tagged("post_install", "-at_install", "swm")
class TestStatusEngine(SwmCommon):

    def test_fill_from_distance(self):
        """Distance + bin height derive the fill percentage."""
        res = self.bin.process_reading(distance_cm=30.0)
        self.assertEqual(res["result"], "ok")
        self.assertAlmostEqual(res["fill_percentage"], 70.0, places=1)

    def test_threshold_ladder(self):
        """available → nearly_full → collection_pending as fill rises."""
        self.bin.process_reading(fill_percentage=20)
        self.assertEqual(self.bin.status, "available")
        self.bin.process_reading(fill_percentage=85)
        self.assertEqual(self.bin.status, "nearly_full")
        self.bin.process_reading(fill_percentage=96)
        # Full trigger immediately creates a request → collection_pending.
        self.assertEqual(self.bin.status, "collection_pending")

    def test_full_creates_collection_request(self):
        self.bin.process_reading(fill_percentage=97)
        req = self.env["otm.swm.collection.request"].search(
            [("bin_id", "=", self.bin.id)])
        self.assertEqual(len(req), 1)
        self.assertEqual(req.staff_id, self.staff,
                         "Association-scoped staff should be auto-assigned")
        self.assertTrue(self.bin.full_since)
        self.assertTrue(self.bin.collection_requested_time)

    def test_hysteresis_no_flutter(self):
        """96 → 94 → 96 around the full threshold must not toggle the
        status back and forth (hysteresis margin)."""
        self.set_param("dedupe_minutes", "0")
        self.bin.process_reading(fill_percentage=96)
        self.assertEqual(self.bin.status, "collection_pending")
        self.bin.process_reading(fill_percentage=94)
        self.assertEqual(
            self.bin.status, "collection_pending",
            "Dropping 2%% below the threshold must not leave full-like state")
        req = self.env["otm.swm.collection.request"].search(
            [("bin_id", "=", self.bin.id)])
        self.assertEqual(len(req), 1, "No duplicate request from flutter")

    def test_empty_detection_completes_request(self):
        """Fill dropping to the empty threshold auto-completes the open
        request with sensor confirmation."""
        self.set_param("dedupe_minutes", "0")
        self.bin.process_reading(fill_percentage=97)
        req = self.env["otm.swm.collection.request"].search(
            [("bin_id", "=", self.bin.id)])
        self.bin.process_reading(fill_percentage=10)
        self.assertEqual(self.bin.status, "collected")
        self.assertEqual(req.state, "done")
        self.assertTrue(req.sensor_confirmed)
        self.assertTrue(self.bin.last_emptied_time)
        history = self.env["otm.swm.collection.history"].search(
            [("bin_id", "=", self.bin.id)])
        self.assertEqual(len(history), 1,
                         "Permanent history row created on completion")

    def test_duplicate_reading_suppressed(self):
        """Identical values inside the dedupe window store one row only."""
        self.set_param("dedupe_minutes", "10")
        self.bin.process_reading(fill_percentage=40)
        res = self.bin.process_reading(fill_percentage=40)
        self.assertTrue(res["duplicate_reading"])
        readings = self.env["otm.swm.sensor.reading"].search(
            [("bin_id", "=", self.bin.id)])
        self.assertEqual(len(readings), 1)

    def test_distinct_reading_stored(self):
        self.set_param("dedupe_minutes", "10")
        self.bin.process_reading(fill_percentage=40)
        res = self.bin.process_reading(fill_percentage=55)
        self.assertFalse(res["duplicate_reading"])
        readings = self.env["otm.swm.sensor.reading"].search(
            [("bin_id", "=", self.bin.id)])
        self.assertEqual(len(readings), 2)

    def test_maintenance_ignores_readings(self):
        self.bin.action_set_maintenance()
        self.bin.process_reading(fill_percentage=99)
        self.assertEqual(self.bin.status, "maintenance")
        req = self.env["otm.swm.collection.request"].search(
            [("bin_id", "=", self.bin.id)])
        self.assertFalse(req, "No request while under maintenance")

    def test_offline_cron(self):
        self.bin.process_reading(fill_percentage=30)
        self.bin.write({"last_communication": fields.Datetime.subtract(
            fields.Datetime.now(), minutes=999)})
        self.env["otm.swm.bin"].cron_check_device_offline()
        self.assertEqual(self.bin.status, "offline")
        self.assertFalse(self.bin.device_online)
