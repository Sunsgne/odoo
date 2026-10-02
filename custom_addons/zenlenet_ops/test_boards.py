import unittest
from datetime import date

from boards import place_bucket, power_ratio, share, top_counts, warranty_bucket


class BoardTests(unittest.TestCase):
    def test_share(self):
        self.assertEqual(share(0, 0), 0)
        self.assertEqual(share(96, 100), 96)

    def test_place(self):
        self.assertEqual(place_bucket('in_rack', 'ok'), 'in_rack')
        self.assertEqual(place_bucket('in_rack', 'repairing'), 'repair')
        self.assertEqual(place_bucket('loan', 'ok'), 'loan')
        self.assertEqual(place_bucket('stock', 'ok'), 'stock')
        self.assertEqual(place_bucket(False, 'ok'), 'unknown')

    def test_warranty(self):
        today = date(2026, 10, 2)
        self.assertEqual(warranty_bucket(today, None), 'unknown')
        self.assertEqual(warranty_bucket(today, date(2024, 1, 1)), 'expired_year')
        self.assertEqual(warranty_bucket(today, date(2026, 6, 1)), 'expired')
        self.assertEqual(warranty_bucket(today, date(2027, 1, 1)), 'within_year')
        self.assertEqual(warranty_bucket(today, date(2028, 1, 1)), 'over_year')

    def test_power(self):
        self.assertEqual(power_ratio(0, 0), {'percent': 0, 'over': False})
        self.assertEqual(power_ratio(202, 0), {'percent': 0, 'over': True})
        self.assertEqual(power_ratio(50, 100), {'percent': 50, 'over': False})
        self.assertEqual(power_ratio(150, 100), {'percent': 100, 'over': True})

    def test_top_counts_skip_blanks(self):
        rows = top_counts([('A', 2), ('', 9), ('B', 2), ('A', 1)], limit=2)
        self.assertEqual(rows, [{'label': 'A', 'count': 3}, {'label': 'B', 'count': 2}])


if __name__ == '__main__':
    unittest.main()
