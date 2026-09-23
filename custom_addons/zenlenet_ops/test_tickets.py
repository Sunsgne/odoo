import unittest
from datetime import datetime, timedelta

from tickets import due_at, is_open, is_overdue, next_state, prev_state, sla_hours


class TicketTests(unittest.TestCase):
    def test_sla_hours_by_priority(self):
        self.assertEqual(sla_hours('3'), 4)
        self.assertEqual(sla_hours('2'), 8)
        self.assertEqual(sla_hours('1'), 24)
        self.assertEqual(sla_hours('0'), 72)
        self.assertEqual(sla_hours('nope'), 24)

    def test_due_and_overdue(self):
        opened = datetime(2026, 9, 23, 8, 0)
        due = due_at(opened, '3')
        self.assertEqual(due, opened + timedelta(hours=4))
        self.assertFalse(is_overdue('processing', due, opened + timedelta(hours=3)))
        self.assertTrue(is_overdue('processing', due, opened + timedelta(hours=5)))
        self.assertFalse(is_overdue('resolved', due, opened + timedelta(hours=5)))
        self.assertFalse(is_overdue('processing', None, opened))

    def test_state_order(self):
        self.assertEqual(next_state('new'), 'assigned')
        self.assertEqual(next_state('assigned'), 'processing')
        self.assertEqual(next_state('processing'), 'resolved')
        self.assertEqual(next_state('resolved'), 'closed')
        self.assertIsNone(next_state('closed'))
        self.assertEqual(next_state('waiting'), 'processing')
        self.assertEqual(prev_state('processing'), 'assigned')
        self.assertEqual(prev_state('waiting'), 'processing')
        self.assertIsNone(prev_state('new'))
        self.assertTrue(is_open('waiting'))
        self.assertFalse(is_open('closed'))


if __name__ == '__main__':
    unittest.main()
