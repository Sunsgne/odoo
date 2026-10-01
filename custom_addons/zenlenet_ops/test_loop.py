import unittest

from loop import can_rebind, capacity_ready, http_policy, operation_result, payload_hash, pick_remote


class LoopRuleTests(unittest.TestCase):
    def test_same_operation_replays(self):
        digest = payload_hash('reserve:prefix:4')
        self.assertEqual(operation_result(digest, digest), 'same')
        self.assertEqual(operation_result(digest, payload_hash('reserve:prefix:5')), 'conflict')

    def test_tombstone_blocks_rebind(self):
        self.assertFalse(can_rebind(True))
        self.assertTrue(can_rebind(False))

    def test_remote_identity_does_not_follow_a_renamed_or_reused_name(self):
        by_id = {7: 'row-7'}
        names = {'GS': 7, 'SG3': 0}
        self.assertEqual(pick_remote(by_id, names, 7, 'SG3'), 'id')
        self.assertEqual(pick_remote(by_id, names, 8, 'SG3'), 'first')
        self.assertEqual(pick_remote(by_id, names, 9, 'GS'), 'conflict')
        self.assertEqual(pick_remote(by_id, names, 9, '新机房'), 'new')
        self.assertEqual(pick_remote(by_id, names, 4, 'SG3', tombstoned_ids=[4]), 'tombstone')
        self.assertEqual(pick_remote({4: 'row-4'}, names, 4, '别的名字', tombstoned_ids=[4]), 'id')

    def test_http_auth_stops_and_rate_limit_retries(self):
        self.assertEqual(http_policy(200), 'ok')
        self.assertEqual(http_policy(401), 'stop')
        self.assertEqual(http_policy(403), 'stop')
        self.assertEqual(http_policy(400), 'fail')
        self.assertEqual(http_policy(429), 'retry')
        self.assertEqual(http_policy(503), 'retry')

    def test_capacity_waits_for_technical_and_metering(self):
        self.assertFalse(capacity_ready(['commercial']))
        self.assertFalse(capacity_ready(['technical']))
        self.assertTrue(capacity_ready(['technical', 'metering']))
        self.assertTrue(capacity_ready(['technical', 'metering', 'supplier']))
