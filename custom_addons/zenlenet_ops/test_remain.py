import unittest

from remain import (
    can_resell,
    inventory_export_allowed,
    next_job,
    next_rollout,
    portal_partner_id,
    power_ok,
    shadow_delta,
    should_apply,
)


class RemainRuleTests(unittest.TestCase):
    def test_older_event_does_not_win(self):
        self.assertTrue(should_apply(None, 1))
        self.assertTrue(should_apply(2, 3))
        self.assertTrue(should_apply(3, 3))
        self.assertFalse(should_apply(4, 2))
        self.assertFalse(should_apply(1, None))

    def test_inventory_export_is_not_for_every_user(self):
        self.assertFalse(inventory_export_allowed(False, False))
        self.assertTrue(inventory_export_allowed(True, False))
        self.assertTrue(inventory_export_allowed(False, True))

    def test_rollout_cannot_skip_to_billing(self):
        self.assertEqual(next_rollout('shadow'), 'hold')
        self.assertEqual(next_rollout('hold'), 'change')
        self.assertEqual(next_rollout('change'), 'bill')
        self.assertIsNone(next_rollout('bill'))

    def test_execute_is_unknown_until_evidence(self):
        self.assertEqual(next_job('draft', False), 'planned')
        self.assertEqual(next_job('planned', False), 'unknown')
        self.assertIsNone(next_job('unknown', False))
        self.assertEqual(next_job('unknown', True), 'verified')

    def test_wipe_without_evidence_cannot_resell(self):
        self.assertFalse(can_resell(''))
        self.assertTrue(can_resell('checksum-ok'))

    def test_shadow_does_not_invent_a_posted_amount(self):
        self.assertEqual(shadow_delta(100, 80), 20.0)
        self.assertEqual(shadow_delta(51.61, 51.61), 0.0)

    def test_power_and_portal_scope(self):
        self.assertTrue(power_ok(10, 0))
        self.assertTrue(power_ok(10, 12))
        self.assertFalse(power_ok(13, 12))
        self.assertFalse(portal_partner_id(True, 5))
        self.assertEqual(portal_partner_id(False, 5), 5)
