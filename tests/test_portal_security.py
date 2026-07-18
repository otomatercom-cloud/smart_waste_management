# Part of Otomater. See LICENSE file for full copyright and licensing details.
from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import SwmCommon


@tagged("post_install", "-at_install", "swm")
class TestPortalSecurity(SwmCommon):

    def setUp(self):
        super().setUp()
        group = self.env.ref(
            "smart_waste_management.group_swm_portal_member")
        self.portal_user = self.env["res.users"].create({
            "name": "Portal Member A",
            "login": "swm_portal_a",
            "group_ids": [(4, group.id)],
        })
        self.member = self.env["otm.swm.association.member"].create({
            "name": "Portal Member A",
            "association_id": self.assoc.id,
            "street_id": self.street.id,
            "user_id": self.portal_user.id,
        })

    def test_portal_sees_only_own_association_bins(self):
        Bin = self.env["otm.swm.bin"].with_user(self.portal_user)
        bins = Bin.search([])
        self.assertIn(self.bin, bins)
        self.assertNotIn(
            self.bin2, bins,
            "Bins of other associations must be invisible to the member")

    def test_portal_cannot_read_other_association_bin(self):
        Bin = self.env["otm.swm.bin"].with_user(self.portal_user)
        with self.assertRaises(AccessError):
            Bin.browse(self.bin2.id).read(["name"])

    def test_portal_cannot_write_bin(self):
        Bin = self.env["otm.swm.bin"].with_user(self.portal_user)
        with self.assertRaises(AccessError):
            Bin.browse(self.bin.id).write({"name": "Hacked"})

    def test_portal_cannot_read_api_token(self):
        """api_token is groups-restricted to the SWM administrator."""
        Bin = self.env["otm.swm.bin"].with_user(self.portal_user)
        rec = Bin.browse(self.bin.id)
        with self.assertRaises(AccessError):
            rec.read(["api_token"])

    def test_portal_requests_scoped(self):
        self.bin.process_reading(fill_percentage=97)
        self.bin2.process_reading(fill_percentage=97)
        Req = self.env["otm.swm.collection.request"].with_user(
            self.portal_user)
        reqs = Req.search([])
        self.assertTrue(all(
            r.association_id == self.assoc for r in reqs),
            "Portal member must only see own-association requests")

    def test_manual_completion_needs_supervisor(self):
        self.bin.process_reading(fill_percentage=97)
        req = self.env["otm.swm.collection.request"].search(
            [("bin_id", "=", self.bin.id)])
        with self.assertRaises(AccessError):
            req.with_user(self.staff_user).action_mark_done()

    def test_supervisor_can_complete_manually(self):
        sup_user = self.env["res.users"].create({
            "name": "Supervisor",
            "login": "swm_sup_test",
            "group_ids": [(4, self.env.ref(
                "smart_waste_management.group_swm_supervisor").id)],
        })
        self.bin.process_reading(fill_percentage=97)
        req = self.env["otm.swm.collection.request"].search(
            [("bin_id", "=", self.bin.id)])
        req.with_user(sup_user).action_mark_done(note="Truck emptied it")
        self.assertEqual(req.state, "done")
        self.assertTrue(req.manual_completion)
        self.assertFalse(req.sensor_confirmed)
