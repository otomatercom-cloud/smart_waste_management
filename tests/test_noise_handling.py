# Part of Otomater. See LICENSE file for full copyright and licensing details.
from odoo.tests import tagged

from .common import SwmCommon


@tagged("post_install", "-at_install", "swm")
class TestNoiseHandling(SwmCommon):

    def test_single_noisy_full_reading_ignored(self):
        """With confirmation=2, one stray full reading must not create a
        collection request; the second consecutive one does."""
        self.set_param("status_confirm_count", "2")
        Request = self.env["otm.swm.collection.request"]
        self.bin.process_reading(fill_percentage=30)
        # A single spurious spike (e.g. hand over the sensor):
        self.bin.process_reading(fill_percentage=97)
        self.assertNotIn(self.bin.status, ("full", "collection_pending"))
        self.assertFalse(Request.search([("bin_id", "=", self.bin.id)]),
                         "One noisy reading must not fire a request")
        # A normal reading resets the pending candidate:
        self.bin.process_reading(fill_percentage=31)
        self.assertFalse(self.bin.pending_status_candidate)
        # Two consecutive genuine full readings do transition:
        self.bin.process_reading(fill_percentage=96)
        self.bin.process_reading(fill_percentage=97)
        self.assertEqual(self.bin.status, "collection_pending")
        self.assertEqual(
            len(Request.search([("bin_id", "=", self.bin.id)])), 1)

    def test_single_noisy_empty_reading_ignored(self):
        """With confirmation=2, one stray low reading (open lid echo)
        must not complete the collection request."""
        self.set_param("status_confirm_count", "1")
        self.bin.process_reading(fill_percentage=97)
        req = self.env["otm.swm.collection.request"].search(
            [("bin_id", "=", self.bin.id)])
        self.set_param("status_confirm_count", "2")
        self.bin.process_reading(fill_percentage=4)  # stray echo
        self.assertEqual(req.state, "assigned",
                         "One noisy empty reading must not complete")
        self.bin.process_reading(fill_percentage=5)  # confirmed empty
        self.assertEqual(req.state, "done")
        self.assertEqual(self.bin.status, "collected")

    def test_live_fields_update_even_when_row_throttled(self):
        """Storage throttle suppresses the DB row but live fill and
        reading time must always refresh (staff QR relies on them)."""
        self.set_param("min_storage_seconds", "3600")
        self.set_param("storage_delta", "50")
        self.bin.process_reading(fill_percentage=40)
        first_time = self.bin.last_reading_time
        res = self.bin.process_reading(fill_percentage=42)
        self.assertTrue(res["duplicate_reading"],
                        "Small change inside throttle window: no row")
        self.assertEqual(self.bin.fill_percentage, 42,
                         "Live fill must still update")
        self.assertGreaterEqual(self.bin.last_reading_time, first_time)
        rows = self.env["otm.swm.sensor.reading"].search(
            [("bin_id", "=", self.bin.id)])
        self.assertEqual(len(rows), 1)

    def test_big_delta_bypasses_throttle(self):
        self.set_param("min_storage_seconds", "3600")
        self.set_param("storage_delta", "5")
        self.bin.process_reading(fill_percentage=40)
        res = self.bin.process_reading(fill_percentage=70)
        self.assertFalse(res["duplicate_reading"],
                         "A 30%% jump must be stored immediately")
        rows = self.env["otm.swm.sensor.reading"].search(
            [("bin_id", "=", self.bin.id)])
        self.assertEqual(len(rows), 2)
