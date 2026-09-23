import unittest

from flow import can_convert, can_reclaim, next_state, prev_state, team_for, transition_allowed


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
        self.assertEqual(seen, ['company', 'allocate', 'deliver', 'accept', 'decide'])
        self.assertIsNone(next_state('test', 'decide'))

    def test_reclaim_finishes(self):
        self.assertEqual(next_state('test', 'reclaim'), 'done')
        self.assertEqual(prev_state('test', 'reclaim'), 'decide')

    def test_business_accept_goes_to_done(self):
        self.assertEqual(next_state('business', 'accept'), 'done')
        self.assertTrue(transition_allowed('business', 'accept', 'business', 'done'))

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
