# Part of Otomater. See LICENSE file for full copyright and licensing details.
from odoo.tests import tagged

from .common import SwmCommon


@tagged("post_install", "-at_install", "swm")
class TestWalletBilling(SwmCommon):

    def setUp(self):
        super().setUp()
        self.member = self.env["otm.swm.association.member"].create({
            "name": "Wallet Test Member",
            "association_id": self.assoc.id,
            "street_id": self.street.id,
        })
        self.plan = self.env["otm.swm.subscription.plan"].create({
            "name": "Metered Household",
            "price": 100.0,        # wallet top-up on renewal
            "duration_days": 30,
            "rate_per_kg": 30.0,   # Rs 30 charged per kg deposited
        })
        self.member.subscription_plan_id = self.plan
        self.member.action_renew_subscription()  # tops wallet to 100
        self.card = self.env["otm.swm.rfid.card"].create({
            "card_uid": "WALLET-CARD-1",
            "holder_type": "member",
            "member_id": self.member.id,
        })
        self.set_param("rfid_enabled", "True")
        self.set_param("weight_capture_enabled", "True")
        self.set_param("wallet_billing_enabled", "True")
        # Per-tap fee defaults to Rs 2 - zeroed here so every existing
        # test in this class keeps testing per-kg billing in isolation,
        # exactly as before. See TestPerTapFee below for the fee itself.
        self.set_param("per_tap_fee", "0")

    def test_renewal_tops_up_wallet(self):
        self.assertAlmostEqual(self.member.wallet_balance, 100.0)

    def test_deposit_bills_wallet_via_explicit_close(self):
        # 3 kg at Rs 30/kg = Rs 90 charged, Rs 10 left from a Rs 100
        # wallet - matches the exact example given.
        self.bin.check_rfid_access("WALLET-CARD-1", weight_kg=0.0)
        self.bin.process_reading(fill_percentage=10, weight_kg=3.0)
        result = self.bin.close_rfid_session(weight_kg=3.0)
        self.assertTrue(result["has_session"])
        self.assertAlmostEqual(result["weight_deposited_kg"], 3.0)
        self.assertAlmostEqual(result["amount_charged"], 90.0)
        self.assertAlmostEqual(result["wallet_balance"], 10.0)
        self.assertAlmostEqual(self.member.wallet_balance, 10.0)

    def test_close_with_no_session_is_safe(self):
        result = self.bin.close_rfid_session()
        self.assertFalse(result["has_session"])

    def test_flat_plan_never_bills(self):
        flat_plan = self.env["otm.swm.subscription.plan"].create({
            "name": "Flat Plan", "price": 50.0, "duration_days": 30,
            "rate_per_kg": 0.0,  # flat - no per-kg rate
        })
        self.member.subscription_plan_id = flat_plan
        self.member.action_renew_subscription()
        balance_before = self.member.wallet_balance
        self.bin.check_rfid_access("WALLET-CARD-1", weight_kg=0.0)
        result = self.bin.close_rfid_session(weight_kg=5.0)
        self.assertAlmostEqual(result["amount_charged"], 0.0)
        self.assertAlmostEqual(self.member.wallet_balance, balance_before)

    def test_billing_disabled_setting_prevents_charge(self):
        self.set_param("wallet_billing_enabled", "False")
        balance_before = self.member.wallet_balance
        self.bin.check_rfid_access("WALLET-CARD-1", weight_kg=0.0)
        result = self.bin.close_rfid_session(weight_kg=5.0)
        self.assertAlmostEqual(result["amount_charged"], 0.0)
        self.assertAlmostEqual(self.member.wallet_balance, balance_before)

    def test_low_balance_denies_next_tap(self):
        self.member.wallet_balance = 0.0
        self.set_param("wallet_low_balance_threshold", "0")
        result = self.bin.check_rfid_access("WALLET-CARD-1")
        self.assertEqual(result["access"], "denied")
        self.assertEqual(result["reason"], "balance_low")

    def test_balance_above_threshold_still_grants(self):
        self.member.wallet_balance = 5.0
        self.set_param("wallet_low_balance_threshold", "0")
        result = self.bin.check_rfid_access("WALLET-CARD-1")
        self.assertEqual(result["access"], "granted")

    def test_early_warning_threshold(self):
        # A positive threshold blocks before the balance hits exactly 0.
        self.member.wallet_balance = 8.0
        self.set_param("wallet_low_balance_threshold", "10")
        result = self.bin.check_rfid_access("WALLET-CARD-1")
        self.assertEqual(result["access"], "denied")
        self.assertEqual(result["reason"], "balance_low")

    def test_balance_can_go_negative_after_overdraw(self):
        # Physical waste already dumped can't be un-dumped - the debt
        # is recorded, and the NEXT tap is what gets blocked, not this
        # one retroactively.
        self.member.wallet_balance = 20.0
        self.bin.check_rfid_access("WALLET-CARD-1", weight_kg=0.0)
        result = self.bin.close_rfid_session(weight_kg=3.0)  # costs 90
        self.assertLess(result["wallet_balance"], 0)
        second = self.bin.check_rfid_access("WALLET-CARD-1")
        self.assertEqual(second["access"], "denied")
        self.assertEqual(second["reason"], "balance_low")

    def test_staff_card_never_touches_wallet(self):
        staff_card = self.env["otm.swm.rfid.card"].create({
            "card_uid": "STAFF-WALLET-TEST",
            "holder_type": "staff",
            "staff_id": self.staff.id,
        })
        balance_before = self.member.wallet_balance
        self.bin.check_rfid_access("STAFF-WALLET-TEST", weight_kg=0.0)
        self.bin.close_rfid_session(weight_kg=10.0)
        self.assertAlmostEqual(self.member.wallet_balance, balance_before)

    def test_rate_change_does_not_retroactively_alter_billing(self):
        self.bin.check_rfid_access("WALLET-CARD-1", weight_kg=0.0)
        log = self.env["otm.swm.bin.access.log"].search(
            [("card_uid", "=", "WALLET-CARD-1")], limit=1, order="id desc")
        original_rate = log.billing_rate_per_kg
        self.assertAlmostEqual(original_rate, 30.0)
        self.plan.rate_per_kg = 50.0  # rate change after the tap opened
        self.bin.close_rfid_session(weight_kg=3.0)
        self.assertAlmostEqual(log.billing_rate_per_kg, original_rate)
        self.assertAlmostEqual(log.amount_charged, 90.0)  # still old rate

    def test_billing_receipt_does_not_break_session_close(self):
        # No Telegram bot is configured in tests, so send_direct safely
        # no-ops - this just confirms the receipt call path (whether
        # on or off) never breaks the actual billing/session close.
        self.member.write({
            "telegram_connected": True,
            "telegram_chat_id": "123456",
        })
        self.set_param("billing_receipt_enabled", "True")
        self.bin.check_rfid_access("WALLET-CARD-1", weight_kg=0.0)
        result = self.bin.close_rfid_session(weight_kg=3.0)
        self.assertTrue(result["has_session"])
        self.assertAlmostEqual(result["amount_charged"], 90.0)

    def test_billing_receipt_disabled_setting_still_bills_correctly(self):
        self.member.write({
            "telegram_connected": True,
            "telegram_chat_id": "123456",
        })
        self.set_param("billing_receipt_enabled", "False")
        self.bin.check_rfid_access("WALLET-CARD-1", weight_kg=0.0)
        result = self.bin.close_rfid_session(weight_kg=3.0)
        self.assertAlmostEqual(result["amount_charged"], 90.0)

    def test_no_receipt_attempt_when_not_connected(self):
        # Member has no Telegram link at all - _send_billing_receipt
        # must return early without error.
        self.bin.check_rfid_access("WALLET-CARD-1", weight_kg=0.0)
        result = self.bin.close_rfid_session(weight_kg=3.0)
        self.assertAlmostEqual(result["amount_charged"], 90.0)


@tagged("post_install", "-at_install", "swm")
class TestPerTapFee(SwmCommon):
    """Flat per-tap usage fee, folded into the same amount_charged
    total as the per-kg weight charge - never a separate line."""

    def setUp(self):
        super().setUp()
        self.member = self.env["otm.swm.association.member"].create({
            "name": "Per-Tap Fee Member",
            "association_id": self.assoc.id,
            "street_id": self.street.id,
        })
        self.plan = self.env["otm.swm.subscription.plan"].create({
            "name": "Metered Household", "price": 100.0,
            "duration_days": 30, "rate_per_kg": 30.0,
        })
        self.member.subscription_plan_id = self.plan
        self.member.action_renew_subscription()  # tops wallet to 100
        self.card = self.env["otm.swm.rfid.card"].create({
            "card_uid": "TAPFEE-CARD-1",
            "holder_type": "member",
            "member_id": self.member.id,
        })
        self.set_param("rfid_enabled", "True")
        self.set_param("weight_capture_enabled", "True")
        self.set_param("wallet_billing_enabled", "True")

    def test_default_fee_is_two_rupees(self):
        settings = self.env["res.config.settings"]
        self.assertAlmostEqual(settings.swm_get_float("per_tap_fee", 2.0), 2.0)

    def test_fee_combined_into_single_amount_charged(self):
        # 3 kg at Rs 30/kg = Rs 90, plus the Rs 2 flat tap fee = Rs 92
        # total - ONE number, not two separate charges anywhere.
        self.bin.check_rfid_access("TAPFEE-CARD-1", weight_kg=0.0)
        result = self.bin.close_rfid_session(weight_kg=3.0)
        self.assertAlmostEqual(result["amount_charged"], 92.0)
        self.assertAlmostEqual(result["wallet_balance"], 8.0)
        self.assertAlmostEqual(self.member.wallet_balance, 8.0)

    def test_fee_still_charged_on_flat_plan(self):
        # A flat/unmetered plan (rate_per_kg = 0) skips the weight
        # charge but the tap itself still costs the flat fee.
        flat_plan = self.env["otm.swm.subscription.plan"].create({
            "name": "Flat Plan", "price": 50.0, "duration_days": 30,
            "rate_per_kg": 0.0,
        })
        self.member.subscription_plan_id = flat_plan
        self.member.action_renew_subscription()
        balance_before = self.member.wallet_balance
        self.bin.check_rfid_access("TAPFEE-CARD-1", weight_kg=0.0)
        result = self.bin.close_rfid_session(weight_kg=5.0)
        self.assertAlmostEqual(result["amount_charged"], 2.0)
        self.assertAlmostEqual(
            self.member.wallet_balance, balance_before - 2.0)

    def test_fee_zero_disables_it(self):
        self.set_param("per_tap_fee", "0")
        self.bin.check_rfid_access("TAPFEE-CARD-1", weight_kg=0.0)
        result = self.bin.close_rfid_session(weight_kg=3.0)
        self.assertAlmostEqual(result["amount_charged"], 90.0)  # weight only

    def test_custom_fee_amount(self):
        self.set_param("per_tap_fee", "5")
        self.bin.check_rfid_access("TAPFEE-CARD-1", weight_kg=0.0)
        result = self.bin.close_rfid_session(weight_kg=3.0)
        self.assertAlmostEqual(result["amount_charged"], 95.0)

    def test_staff_tap_never_charged_fee(self):
        staff_card = self.env["otm.swm.rfid.card"].create({
            "card_uid": "STAFF-TAPFEE-TEST",
            "holder_type": "staff",
            "staff_id": self.staff.id,
        })
        balance_before = self.member.wallet_balance
        self.bin.check_rfid_access("STAFF-TAPFEE-TEST", weight_kg=0.0)
        self.bin.close_rfid_session(weight_kg=10.0)
        self.assertAlmostEqual(self.member.wallet_balance, balance_before)
