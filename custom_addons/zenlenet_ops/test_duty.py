import unittest
from datetime import date

from duty import (
    apply_swap,
    coverage,
    month_days,
    next_state,
    offset_label,
    overnight,
    parse_hhmm,
    person_counts,
    week_days,
    weekday_label,
)


class DutyTests(unittest.TestCase):
    def test_clock(self):
        self.assertEqual(parse_hhmm('09:00'), 540)
        self.assertIsNone(parse_hhmm('9:00'))
        self.assertIsNone(parse_hhmm('24:00'))
        self.assertTrue(overnight('21:00', '09:00'))
        self.assertFalse(overnight('09:00', '21:00'))
        self.assertFalse(overnight('07:00', '16:00'))

    def test_week_starts_on_sunday(self):
        days = week_days(date(2026, 10, 2), 'sun')
        self.assertEqual(days[0], date(2026, 9, 27))
        self.assertEqual(days[-1], date(2026, 10, 3))
        self.assertEqual(weekday_label(days[0]), '日')
        self.assertEqual(weekday_label(days[-1]), '六')
        self.assertEqual(week_days(date(2026, 10, 2), 'mon')[0], date(2026, 9, 28))

    def test_month_covers_the_edges(self):
        days = month_days(date(2026, 10, 2), 'sun')
        self.assertEqual(days[0].weekday(), 6)
        self.assertIn(date(2026, 10, 1), days)
        self.assertIn(date(2026, 10, 31), days)
        self.assertEqual(len(days) % 7, 0)

    def test_offset(self):
        self.assertEqual(offset_label('Asia/Singapore', date(2026, 10, 2)), 'UTC+08:00')
        self.assertEqual(offset_label('UTC', date(2026, 10, 2)), 'UTC+00:00')

    def test_coverage_and_people(self):
        rows = [
            {'need': 2, 'filled': 2, 'people': [{'id': 1}, {'id': 2}]},
            {'need': 1, 'filled': 0, 'people': []},
        ]
        self.assertEqual(coverage(rows), {'need': 3, 'filled': 2, 'rate': 67})
        self.assertEqual(person_counts(rows), [(1, 1), (2, 1)])

    def test_swap_exchanges_the_two_people(self):
        self.assertIsNone(apply_swap({1}, {2}, 1, 1))
        self.assertIsNone(apply_swap({3}, {2}, 1, 2))
        source, dest = apply_swap({1, 4}, {2, 5}, 1, 2)
        self.assertEqual(source, {2, 4})
        self.assertEqual(dest, {1, 5})

    def test_swap_flow(self):
        self.assertEqual(next_state('draft', 'submit'), 'peer')
        self.assertEqual(next_state('peer', 'peer'), 'lead')
        self.assertEqual(next_state('lead', 'approve'), 'approved')
        self.assertEqual(next_state('peer', 'refuse'), 'refused')
        self.assertEqual(next_state('lead', 'withdraw'), 'withdrawn')
        self.assertIsNone(next_state('approved', 'withdraw'))


if __name__ == '__main__':
    unittest.main()
