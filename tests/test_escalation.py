# Part of Otomater. See LICENSE file for full copyright and licensing details.
from odoo import fields

from odoo.tests import tagged

from .common import SwmCommon


@tagged("post_install", "-at_install", "swm")
class TestEscalation(SwmCommon):

    def _make_request(self, hours_ago):
        self.bin.process_reading(fill_percentage=97)
        req = self.env["otm.swm.collection.request"].search(
            [("bin_id", "=", self.bin.id)])
        req.write({"full_detected_time": fields.Datetime.subtract(
            fields.Datetime.now(), hours=hours_ago)})
        return req

    def test_no_escalation_before_delay(self):
        req = self._make_request(hours_ago=1)
        self.env["otm.swm.notification.rule"].process_delayed(req)
        self.assertEqual(req.escalation_level, 0)

    def test_level1_after_2h(self):
        req = self._make_request(hours_ago=3)
        self.env["otm.swm.notification.rule"].process_delayed(req)
        self.assertEqual(req.escalation_level, 1)
        # Fired rules are recorded → running again must not duplicate.
        fired = len(req.fired_rule_ids)
        self.env["otm.swm.notification.rule"].process_delayed(req)
        self.assertEqual(len(req.fired_rule_ids), fired,
                         "Non-recurring rules fire once per request")

    def test_level3_after_24h(self):
        req = self._make_request(hours_ago=25)
        self.env["otm.swm.notification.rule"].process_delayed(req)
        self.assertEqual(req.escalation_level, 3,
                         "All ladder levels due after 24h; level is the max")
        # Every attempt is logged, even without Telegram configured.
        logs = self.env["otm.swm.notification.log"].search(
            [("request_id", "=", req.id),
             ("trigger_type", "=", "collection_delayed")])
        self.assertTrue(logs, "Escalation attempts must be logged")

    def test_configurable_delay(self):
        """Changing the rule delay changes when it fires — nothing is
        hardcoded to 24h."""
        rule = self.env["otm.swm.notification.rule"].search(
            [("trigger_type", "=", "collection_delayed"),
             ("escalation_level", "=", 1)], limit=1)
        self.assertTrue(rule)
        rule.write({"delay_number": 30, "delay_unit": "minutes"})
        req = self._make_request(hours_ago=1)
        self.env["otm.swm.notification.rule"].process_delayed(req)
        self.assertEqual(req.escalation_level, 1,
                         "Rule fires after its configured 30 minutes")

    def test_completed_request_records_response_time(self):
        req = self._make_request(hours_ago=2)
        self.set_param("dedupe_minutes", "0")
        self.bin.process_reading(fill_percentage=5)
        self.assertEqual(req.state, "done")
        self.assertGreaterEqual(req.response_hours, 1.9)
