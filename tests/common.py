# Part of Otomater. See LICENSE file for full copyright and licensing details.
from odoo.tests import TransactionCase


class SwmCommon(TransactionCase):
    """Shared fixture: one corporation → zone → ward → association →
    street → bin chain plus a collection staff record."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.corp = env["otm.swm.corporation"].create({
            "name": "Test Corporation",
            "code": "TCORP",
            "body_type": "corporation",
        })
        cls.zone = env["otm.swm.zone"].create({
            "name": "Test Zone",
            "corporation_id": cls.corp.id,
        })
        cls.ward = env["otm.swm.ward"].create({
            "name": "Test Ward",
            "zone_id": cls.zone.id,
            "corporation_id": cls.corp.id,
        })
        cls.assoc = env["otm.swm.association"].create({
            "name": "Test Association",
            "code": "TA",
            "corporation_id": cls.corp.id,
            "ward_id": cls.ward.id,
        })
        cls.assoc2 = env["otm.swm.association"].create({
            "name": "Other Association",
            "code": "OA",
            "corporation_id": cls.corp.id,
            "ward_id": cls.ward.id,
        })
        cls.street = env["otm.swm.street"].create({
            "name": "Test Street",
            "association_id": cls.assoc.id,
        })
        cls.staff_user = env["res.users"].create({
            "name": "Test Collector",
            "login": "swm_test_collector",
            "group_ids": [(4, env.ref(
                "smart_waste_management.group_swm_collection_staff").id)],
        })
        cls.staff = env["otm.swm.staff"].create({
            "name": "Test Collector",
            "user_id": cls.staff_user.id,
            "association_ids": [(4, cls.assoc.id)],
        })
        cls.bin = env["otm.swm.bin"].create({
            "name": "Test Bin",
            "association_id": cls.assoc.id,
            "street_id": cls.street.id,
            "bin_height_cm": 100.0,
            "device_id": "ESP32-TEST-01",
        })
        cls.bin2 = env["otm.swm.bin"].create({
            "name": "Other Bin",
            "association_id": cls.assoc2.id,
            "bin_height_cm": 100.0,
            "device_id": "ESP32-TEST-02",
        })
        # Most engine tests assert single-reading transitions; the noise
        # debounce (status_confirm_count, default 2) is exercised by its
        # own dedicated tests.
        env["ir.config_parameter"].sudo().set_param(
            "smart_waste_management.status_confirm_count", "1")

    def set_param(self, key, value):
        self.env["ir.config_parameter"].sudo().set_param(
            f"smart_waste_management.{key}", value)
