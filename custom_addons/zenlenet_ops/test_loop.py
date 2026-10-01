import unittest

from loop import can_rebind, capacity_ready, operation_result, payload_hash


class LoopRuleTests(unittest.TestCase):
    def test_same_operation_replays(self):
        digest = payload_hash('reserve:prefix:4')
        self.assertEqual(operation_result(digest, digest), 'same')
        self.assertEqual(operation_result(digest, payload_hash('reserve:prefix:5')), 'conflict')

    def test_tombstone_blocks_rebind(self):
        self.assertFalse(can_rebind(True))
        self.assertTrue(can_rebind(False))

    def test_capacity_waits_for_technical_and_metering(self):
        self.assertFalse(capacity_ready(['commercial']))
        self.assertFalse(capacity_ready(['technical']))
        self.assertTrue(capacity_ready(['technical', 'metering']))
        self.assertTrue(capacity_ready(['technical', 'metering', 'supplier']))
