import unittest
from datetime import date

from billing import (
    add_months,
    bills_this_period,
    contract_end,
    contract_status,
    cycle_amount,
    period_bounds,
    period_label,
    period_ref,
)


class BillingTests(unittest.TestCase):
    def test_month_arithmetic_clamps_the_day(self):
        self.assertEqual(add_months(date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(add_months(date(2026, 11, 15), 2), date(2027, 1, 15))

    def test_period_labels(self):
        self.assertEqual(period_label(date(2026, 9, 23)), '2026-09')
        self.assertEqual(period_ref(42, date(2026, 9, 23)), 'ZL-202609-42')
        self.assertEqual(period_bounds(date(2026, 2, 10)), (date(2026, 2, 1), date(2026, 2, 28)))

    def test_contract_end_is_inclusive(self):
        self.assertEqual(contract_end(date(2026, 1, 1), 12), date(2026, 12, 31))
        self.assertEqual(contract_end(date(2026, 3, 15), 1), date(2026, 4, 14))
        self.assertIsNone(contract_end(None, 12))
        self.assertIsNone(contract_end(date(2026, 1, 1), 0))

    def test_contract_status_follows_the_calendar(self):
        end = date(2026, 12, 31)
        self.assertEqual(contract_status('active', end, date(2026, 6, 1)), 'active')
        self.assertEqual(contract_status('active', end, date(2026, 12, 10)), 'expiring')
        self.assertEqual(contract_status('expiring', end, date(2027, 1, 1)), 'expired')
        self.assertEqual(contract_status('draft', end, date(2027, 1, 1)), 'draft')
        self.assertEqual(contract_status('terminated', end, date(2027, 1, 1)), 'terminated')
        self.assertEqual(contract_status('active', None, date(2027, 1, 1)), 'active')

    def test_cycle_amounts_and_anniversaries(self):
        self.assertEqual(cycle_amount(100.0, 'monthly'), 100.0)
        self.assertEqual(cycle_amount(100.0, 'quarterly'), 300.0)
        self.assertEqual(cycle_amount(100.0, 'yearly'), 1200.0)
        start = date(2026, 1, 1)
        self.assertTrue(bills_this_period('monthly', date(2026, 5, 1), start))
        self.assertTrue(bills_this_period('quarterly', date(2026, 4, 1), start))
        self.assertFalse(bills_this_period('quarterly', date(2026, 5, 1), start))
        self.assertTrue(bills_this_period('yearly', date(2027, 1, 1), start))
        self.assertFalse(bills_this_period('yearly', date(2026, 7, 1), start))


if __name__ == '__main__':
    unittest.main()
