import unittest
from datetime import date

from meter import (
    aggregate_series,
    commit_overage_amount,
    counter_bps,
    nearest_rank_p95,
    parse_samples,
    prorate,
)


class MeterTests(unittest.TestCase):
    def test_aggregate_p95_is_not_the_sum_of_port_p95(self):
        port_a = [100.0] * 10 + [0.0] * 10
        port_b = [0.0] * 10 + [100.0] * 10
        self.assertEqual(nearest_rank_p95(port_a), 100.0)
        self.assertEqual(nearest_rank_p95(port_b), 100.0)
        combined = aggregate_series([port_a, port_b])
        self.assertEqual(combined, [100.0] * 20)
        self.assertEqual(nearest_rank_p95(combined), 100.0)
        self.assertNotEqual(nearest_rank_p95(port_a) + nearest_rank_p95(port_b), nearest_rank_p95(combined))

    def test_missing_sample_is_not_zero(self):
        self.assertEqual(parse_samples('100, ,0'), [100.0, None, 0.0])
        self.assertEqual(aggregate_series([[100.0, None], [None, None]]), [100.0, None])
        self.assertEqual(nearest_rank_p95([100.0, None]), 100.0)
        self.assertIsNone(nearest_rank_p95([None, None]))

    def test_commit_plus_overage(self):
        self.assertEqual(commit_overage_amount(100, 80, 2, 3), 220.0)
        self.assertEqual(commit_overage_amount(50, 80, 2, 3), 160.0)

    def test_partial_month(self):
        self.assertEqual(prorate(100, date(2026, 10, 16), date(2026, 10, 1), date(2026, 11, 1)), 51.61)

    def test_counter_restart_is_not_negative_usage(self):
        self.assertAlmostEqual(counter_bps(1_000_000, 300), 26666.666666666668)
        self.assertIsNone(counter_bps(-1, 300))
        self.assertIsNone(counter_bps(100, 0))
