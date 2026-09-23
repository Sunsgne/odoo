import unittest
from datetime import date

from billing import (
    add_months,
    bandwidth_lines,
    billing_anchor,
    bills_this_period,
    clean_label,
    contract_end,
    credit_amount,
    customer_month_status,
    fee_due,
    fee_note,
    next_due_month,
    outage_hours,
    parse_period,
    period_title,
    contract_status,
    cycle_amount,
    period_bounds,
    period_label,
    period_ref,
    p95_billable,
    refine_month_status,
    shift_month,
    state_for_month,
    worst_status,
)


class BillingTests(unittest.TestCase):
    def test_burstable_billing_follows_the_95th_percentile(self):
        self.assertEqual(p95_billable(500, 320), 500.0)
        self.assertEqual(p95_billable(500, 640), 640.0)
        self.assertEqual(bandwidth_lines(500, None, 6.0), [('commit', 500.0, 6.0)])
        self.assertEqual(bandwidth_lines(500, 320, 6.0, 8.0), [('commit', 500.0, 6.0)])
        self.assertEqual(bandwidth_lines(500, 640, 6.0, 8.0), [('commit', 500.0, 6.0), ('overage', 140.0, 8.0)])
        self.assertEqual(bandwidth_lines(500, 640, 6.0), [('commit', 640.0, 6.0)])

    def test_outage_credits(self):
        from datetime import datetime
        self.assertEqual(outage_hours(datetime(2026, 9, 1, 8, 0), datetime(2026, 9, 1, 11, 30)), 3.5)
        self.assertEqual(outage_hours(datetime(2026, 9, 1, 8, 0), None), 0.0)
        self.assertEqual(credit_amount(3000, 'hours', hours=3.5, rate=5), 525.0)
        self.assertEqual(credit_amount(3000, 'hours', hours=40, rate=5), 3000.0)
        self.assertEqual(credit_amount(3000, 'hours', hours=40, rate=5, cap_ratio=0.5), 1500.0)
        self.assertEqual(credit_amount(3000, 'percent', rate=10), 300.0)
        self.assertEqual(credit_amount(3000, 'amount', amount=200), 200.0)
        self.assertEqual(credit_amount(3000, 'amount', amount=-5), 0.0)

    def test_labels_lose_their_codes(self):
        self.assertEqual(clean_label('[colo] 托管'), '托管')
        self.assertEqual(clean_label('  IPT 带宽 500M '), 'IPT 带宽 500M')
        self.assertEqual(clean_label(None), '')
        self.assertEqual(clean_label('[pl]'), '')

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

    def test_natural_month_is_the_billing_window(self):
        september = date(2026, 9, 1)
        self.assertEqual(parse_period('2026-09', date(2026, 1, 2)), date(2026, 9, 1))
        self.assertEqual(parse_period('nope', date(2026, 9, 23)), date(2026, 9, 1))
        self.assertEqual(shift_month(date(2026, 9, 15), -1), date(2026, 8, 1))
        self.assertEqual(period_title(september), '2026年9月')
        self.assertEqual(billing_anchor(september, 5, date(2026, 9, 2)), date(2026, 9, 2))
        self.assertEqual(billing_anchor(date(2026, 8, 1), 5, date(2026, 9, 2)), date(2026, 8, 5))
        self.assertTrue(fee_due('one_time', 'monthly', september, date(2026, 9, 15), None, False))
        self.assertFalse(fee_due('one_time', 'monthly', september, date(2026, 10, 1), None, False))
        self.assertFalse(fee_due('one_time', 'monthly', september, date(2026, 9, 1), None, True))
        self.assertFalse(fee_due('recurring', 'quarterly', september, date(2026, 1, 1), None, False))
        self.assertTrue(fee_due('recurring', 'quarterly', date(2026, 4, 1), date(2026, 1, 1), None, False))
        self.assertEqual(next_due_month('quarterly', date(2026, 1, 1), september), '2026-10')
        self.assertIn('2026-10', fee_note('active', 'recurring', 'quarterly', september, date(2026, 1, 1), None, False, False))
        self.assertEqual(state_for_month('expired', date(2026, 9, 15), date(2026, 9, 1)), 'active')
        self.assertEqual(state_for_month('expired', date(2026, 9, 15), date(2026, 10, 1)), 'expired')
        self.assertEqual(state_for_month('draft', date(2026, 12, 31), september), 'draft')
        self.assertEqual(state_for_month('terminated', date(2026, 12, 31), september), 'terminated')

    def test_each_customer_month_has_one_status(self):
        self.assertEqual(customer_month_status(100, 0, 0, 0, 0), ('missing', 0.0))
        self.assertEqual(customer_month_status(-20, 0, 0, 0, 0), ('missing', 0.0))
        self.assertEqual(customer_month_status(100, 80, 80, 0, 1), ('unpaid', 20.0))
        self.assertEqual(customer_month_status(100, 100, 40, 0, 1), ('partial', 0.0))
        self.assertEqual(customer_month_status(100, 100, 0, 0, 1), ('paid', 0.0))
        self.assertEqual(customer_month_status(100, 100, 100, 1, 0), ('draft', 0.0))
        self.assertEqual(customer_month_status(100, 100, 50, 1, 1), ('mixed', 0.0))
        self.assertEqual(customer_month_status(0, 0, 0, 0, 0, quote_only=True), ('quote', 0.0))
        self.assertEqual(refine_month_status('skip', False, 1, False, 0), 'draft_contract')
        self.assertEqual(refine_month_status('quote', False, 0, True, 0), 'naked')
        self.assertEqual(refine_month_status('skip', True, 0, True, 0), 'no_items')
        self.assertEqual(refine_month_status('skip', True, 0, True, 2), 'skip')
        self.assertEqual(worst_status(['paid', 'missing']), 'missing')


if __name__ == '__main__':
    unittest.main()
