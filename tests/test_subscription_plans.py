# Part of Otomater. See LICENSE file for full copyright and licensing details.
from odoo import fields
from odoo.tests import tagged

from .common import SwmCommon


@tagged("post_install", "-at_install", "swm")
class TestSubscriptionPlans(SwmCommon):

    def setUp(self):
        super().setUp()
        self.member = self.env["otm.swm.association.member"].create({
            "name": "Plan Test Member",
            "association_id": self.assoc.id,
            "street_id": self.street.id,
        })
        self.plan = self.env["otm.swm.subscription.plan"].create({
            "name": "Monthly Household",
            "price": 100.0,
            "duration_days": 30,
        })

    def test_renew_with_plan_uses_plan_duration_and_price(self):
        self.member.subscription_plan_id = self.plan
        self.member.action_renew_subscription()
        self.assertTrue(self.member.subscription_active)
        self.assertEqual(
            self.member.subscription_expiry,
            fields.Date.add(fields.Date.today(), days=30))
        payment = self.env["otm.swm.subscription.payment"].search(
            [("member_id", "=", self.member.id)], limit=1)
        self.assertEqual(payment.amount, 100.0)
        self.assertEqual(payment.plan_name, "Monthly Household")

    def test_renew_without_plan_falls_back_to_global_setting(self):
        self.set_param("subscription_renewal_days", "45")
        self.member.action_renew_subscription()
        self.assertEqual(
            self.member.subscription_expiry,
            fields.Date.add(fields.Date.today(), days=45))
        payment = self.env["otm.swm.subscription.payment"].search(
            [("member_id", "=", self.member.id)], limit=1)
        self.assertEqual(payment.amount, 0.0)
        self.assertIn("no plan", payment.plan_name.lower())

    def test_price_change_does_not_rewrite_past_payments(self):
        self.member.subscription_plan_id = self.plan
        self.member.action_renew_subscription()
        first_payment = self.env["otm.swm.subscription.payment"].search(
            [("member_id", "=", self.member.id)], limit=1)
        self.assertEqual(first_payment.amount, 100.0)

        self.plan.price = 150.0  # price increase after the fact
        self.assertEqual(
            first_payment.amount, 100.0,
            "Past payment must keep the price that applied at the time")

        self.member.action_renew_subscription()
        second_payment = self.env["otm.swm.subscription.payment"].search(
            [("member_id", "=", self.member.id)],
            order="id desc", limit=1)
        self.assertEqual(second_payment.amount, 150.0)

    def test_member_count_on_plan(self):
        self.member.subscription_plan_id = self.plan
        self.assertEqual(self.plan.member_count, 1)

    def test_plan_deleted_payment_keeps_snapshot(self):
        self.member.subscription_plan_id = self.plan
        self.member.action_renew_subscription()
        payment = self.env["otm.swm.subscription.payment"].search(
            [("member_id", "=", self.member.id)], limit=1)
        self.plan.unlink()
        self.assertEqual(payment.plan_name, "Monthly Household")
        self.assertEqual(payment.amount, 100.0)
        self.assertFalse(payment.plan_id)

    def test_normal_renewal_never_flagged_underpaid(self):
        self.member.subscription_plan_id = self.plan
        self.member.action_renew_subscription()
        payment = self.env["otm.swm.subscription.payment"].search(
            [("member_id", "=", self.member.id)], limit=1)
        self.assertFalse(payment.is_underpaid)

    def test_manual_partial_payment_flagged_underpaid(self):
        payment = self.env["otm.swm.subscription.payment"].create({
            "member_id": self.member.id,
            "plan_id": self.plan.id,
            "plan_name": self.plan.name,
            "amount": 60.0,  # less than the plan's 100.0 price
        })
        self.assertTrue(payment.is_underpaid)
        self.assertEqual(payment.plan_price_at_payment, 100.0)

    def test_full_manual_payment_not_flagged(self):
        payment = self.env["otm.swm.subscription.payment"].create({
            "member_id": self.member.id,
            "plan_id": self.plan.id,
            "plan_name": self.plan.name,
            "amount": 100.0,
        })
        self.assertFalse(payment.is_underpaid)

    def test_underpaid_snapshot_survives_later_price_change(self):
        payment = self.env["otm.swm.subscription.payment"].create({
            "member_id": self.member.id,
            "plan_id": self.plan.id,
            "plan_name": self.plan.name,
            "amount": 90.0,  # less than the 100.0 plan price
        })
        self.assertTrue(payment.is_underpaid)
        self.plan.price = 200.0  # raise price after the fact
        self.assertEqual(
            payment.plan_price_at_payment, 100.0,
            "Reference price must stay the snapshot, not track the "
            "plan's current price")
