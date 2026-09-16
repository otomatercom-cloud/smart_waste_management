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


@tagged("post_install", "-at_install", "swm")
class TestWeightLimitNotification(SwmCommon):

    def setUp(self):
        super().setUp()
        self.set_param("weight_capture_enabled", "True")
        self.set_param("weight_lock_threshold_kg", "10")

    def test_crossing_threshold_sets_notified_flag_once(self):
        self.bin.process_reading(fill_percentage=10, weight_kg=8.0)
        self.assertFalse(self.bin.weight_limit_notified)
        self.bin.process_reading(fill_percentage=10, weight_kg=11.0)
        self.assertTrue(self.bin.weight_limit_notified)

    def test_repeat_readings_over_threshold_do_not_retrigger(self):
        self.bin.process_reading(fill_percentage=10, weight_kg=11.0)
        self.assertTrue(self.bin.weight_limit_notified)
        # Further pings while still over threshold must not error or
        # need to do anything different - flag simply stays set.
        self.bin.process_reading(fill_percentage=10, weight_kg=12.0)
        self.assertTrue(self.bin.weight_limit_notified)

    def test_dropping_below_then_crossing_again_notifies_again(self):
        self.bin.process_reading(fill_percentage=10, weight_kg=11.0)
        self.assertTrue(self.bin.weight_limit_notified)
        self.bin.process_reading(fill_percentage=10, weight_kg=3.0)
        self.assertFalse(self.bin.weight_limit_notified)
        self.bin.process_reading(fill_percentage=10, weight_kg=11.0)
        self.assertTrue(self.bin.weight_limit_notified)

    def test_zero_threshold_never_sets_flag(self):
        self.set_param("weight_lock_threshold_kg", "0")
        self.bin.process_reading(fill_percentage=10, weight_kg=999.0)
        self.assertFalse(self.bin.weight_limit_notified)

    def test_collection_confirm_resets_flag(self):
        self.bin.process_reading(fill_percentage=97, weight_kg=11.0)
        self.assertTrue(self.bin.weight_limit_notified)
        self.bin.write({"fill_percentage": 5,
                        "last_reading_time": fields.Datetime.now()})
        self.bin.qr_confirm_collection()
        self.assertFalse(self.bin.weight_limit_notified)
