import unittest

from flow import (
    can_convert, can_reclaim, next_state, normalize_assignment, prev_state,
    resource_reference, resource_slot, team_for, transition_allowed,
)


class FlowTests(unittest.TestCase):
    def test_business_runs_through_to_done(self):
        state = 'company'
        seen = [state]
        while True:
            state = next_state('business', state)
            if not state:
                break
            seen.append(state)
        self.assertEqual(seen, ['company', 'allocate', 'deliver', 'accept', 'done'])

    def test_test_stops_at_the_decision(self):
        state = 'company'
        seen = [state]
        while True:
            nxt = next_state('test', state)
            if not nxt:
                break
            seen.append(nxt)
            state = nxt
        self.assertEqual(seen, ['company', 'allocate', 'deliver', 'accept'])
        self.assertIsNone(next_state('test', 'accept'))
        self.assertIsNone(next_state('test', 'decide'))

    def test_reclaim_finishes(self):
        self.assertEqual(next_state('test', 'reclaim'), 'done')
        self.assertEqual(prev_state('test', 'reclaim'), 'decide')

    def test_business_accept_goes_to_done(self):
        self.assertEqual(next_state('business', 'accept'), 'done')
        self.assertTrue(transition_allowed('business', 'accept', 'business', 'done'))

    def test_one_slot_per_business(self):
        self.assertEqual(resource_slot('ipt'), 'prefix')
        self.assertEqual(resource_slot('ip_single'), 'address')
        self.assertEqual(resource_slot('sdwan'), 'line')
        self.assertIsNone(resource_slot('vm'))
        self.assertEqual(normalize_assignment('ipt', 5, 9, 3), (5, None, None))
        self.assertEqual(normalize_assignment('pl', 5, None, 3), (None, None, 3))
        self.assertEqual(normalize_assignment('colo', 5, 9, 3), (None, None, None))
        self.assertEqual(normalize_assignment('ip_single', resource_ref='zenlenet.address,12'), (None, 12, None))
        self.assertEqual(resource_reference(5, None, None), 'zenlenet.prefix,5')
        self.assertFalse(resource_reference(None, None, None))

    def test_cannot_skip(self):
        self.assertFalse(transition_allowed('business', 'company', 'business', 'deliver'))
        self.assertFalse(transition_allowed('test', 'decide', 'test', 'done'))
        self.assertFalse(transition_allowed('business', 'done', 'business', 'accept'))

    def test_test_endings(self):
        self.assertTrue(can_reclaim('test', 'accept'))
        self.assertTrue(can_reclaim('test', 'decide'))
        self.assertFalse(can_reclaim('test', 'deliver'))
        self.assertFalse(can_reclaim('business', 'accept'))
        for state in ('accept', 'decide', 'reclaim'):
            self.assertTrue(can_convert('test', state))
            self.assertTrue(transition_allowed('test', state, 'business', 'deliver'))
        self.assertFalse(can_convert('business', 'accept'))
        self.assertFalse(can_convert('test', 'deliver'))

    def test_back_one_step_only(self):
        self.assertEqual(prev_state('business', 'allocate'), 'company')
        self.assertIsNone(prev_state('business', 'company'))
        self.assertTrue(transition_allowed('test', 'deliver', 'test', 'allocate'))

    def test_people_are_grouped_by_stage(self):
        self.assertEqual(team_for('company'), 'sales')
        self.assertEqual(team_for('allocate'), 'delivery')
        self.assertEqual(team_for('deliver'), 'delivery')
        for state in ('accept', 'decide', 'reclaim', 'done'):
            self.assertEqual(team_for(state), 'service')
        self.assertIsNone(team_for('cancel'))


if __name__ == '__main__':
    unittest.main()
