# Part of Otomater. See LICENSE file for full copyright and licensing details.
from odoo.tests import tagged

from .common import SwmCommon


@tagged("post_install", "-at_install", "swm")
class TestSubscriptionApproval(SwmCommon):

    def setUp(self):
        super().setUp()
        self.member = self.env["otm.swm.association.member"].create({
            "name": "Approval Test Member",
            "association_id": self.assoc.id,
            "street_id": self.street.id,
        })
        self.plan = self.env["otm.swm.subscription.plan"].create({
            "name": "Approval Plan", "price": 100.0,
            "duration_days": 30, "rate_per_kg": 30.0,
        })
        self.member.subscription_plan_id = self.plan

    def test_manager_renewal_still_auto_approved(self):
        """Existing Renew Subscription behaviour must not regress: it
        still applies immediately, no approval step in the way."""
        self.member.action_renew_subscription()
        self.assertEqual(self.member.wallet_balance, 100.0)
        payment = self.env["otm.swm.subscription.payment"].search(
            [("member_id", "=", self.member.id)], limit=1)
        self.assertEqual(payment.state, "approved")
        self.assertFalse(payment.is_self_service)

    def test_self_service_request_does_not_apply_immediately(self):
        self.member.action_request_subscription_payment()
        self.assertEqual(
            self.member.wallet_balance, 0.0,
            "Pending request must not touch the wallet until approved")
        self.assertFalse(self.member.subscription_expiry)
        payment = self.env["otm.swm.subscription.payment"].search(
            [("member_id", "=", self.member.id)], limit=1)
        self.assertEqual(payment.state, "pending")
        self.assertTrue(payment.is_self_service)
        self.assertEqual(payment.amount, 100.0)

    def test_request_requires_a_plan(self):
        no_plan_member = self.env["otm.swm.association.member"].create({
            "name": "No Plan Member",
            "association_id": self.assoc.id,
            "street_id": self.street.id,
        })
        result = no_plan_member.action_request_subscription_payment()
        self.assertFalse(result)
        self.assertFalse(self.env["otm.swm.subscription.payment"].search(
            [("member_id", "=", no_plan_member.id)]))

    def test_approve_applies_wallet_and_expiry(self):
        self.member.action_request_subscription_payment()
        payment = self.env["otm.swm.subscription.payment"].search(
            [("member_id", "=", self.member.id)], limit=1)
        payment.action_approve()
        self.assertEqual(payment.state, "approved")
        self.assertEqual(self.member.wallet_balance, 100.0)
        self.assertTrue(self.member.subscription_active)
        self.assertTrue(self.member.subscription_valid)
        self.assertTrue(payment.approved_by_id)
        self.assertTrue(payment.approved_date)

    def test_reject_never_touches_wallet(self):
        self.member.action_request_subscription_payment()
        payment = self.env["otm.swm.subscription.payment"].search(
            [("member_id", "=", self.member.id)], limit=1)
        payment.action_reject()
        self.assertEqual(payment.state, "rejected")
        self.assertEqual(self.member.wallet_balance, 0.0)
        self.assertFalse(self.member.subscription_active)

    def test_cannot_approve_twice(self):
        self.member.action_request_subscription_payment()
        payment = self.env["otm.swm.subscription.payment"].search(
            [("member_id", "=", self.member.id)], limit=1)
        payment.action_approve()
        balance_after_first = self.member.wallet_balance
        payment.action_approve()  # already approved - must be a no-op
        self.assertEqual(self.member.wallet_balance, balance_after_first)

    def test_two_pending_requests_only_first_approved_applies_once(self):
        self.member.action_request_subscription_payment()
        self.member.action_request_subscription_payment()
        payments = self.env["otm.swm.subscription.payment"].search(
            [("member_id", "=", self.member.id)])
        self.assertEqual(len(payments), 2)
        payments[0].action_approve()
        self.assertEqual(self.member.wallet_balance, 100.0)
        payments[1].action_approve()
        self.assertEqual(self.member.wallet_balance, 200.0)
