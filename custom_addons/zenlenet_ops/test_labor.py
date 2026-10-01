import unittest

from labor import clock_hours, labor_amount


class LaborPricingTests(unittest.TestCase):
    def test_same_clock_does_not_invent_hours(self):
        self.assertEqual(clock_hours('16:58', '16:58'), 0.0)

    def test_clock_span(self):
        self.assertEqual(clock_hours('16:00', '17:30'), 1.5)
        self.assertEqual(clock_hours('16：00', '18:00'), 2.0)

    def test_half_day_is_not_multiplied_by_clock_hours(self):
        self.assertEqual(labor_amount(1, 170), 170.0)
        self.assertEqual(clock_hours('16:58', '16:58'), 0.0)

    def test_two_half_days(self):
        self.assertEqual(labor_amount(2, 170), 340.0)

    def test_hourly_quantity(self):
        self.assertEqual(labor_amount(1.5, 80), 120.0)

    def test_blank_price_is_zero(self):
        self.assertEqual(labor_amount(1, 0), 0.0)
        self.assertEqual(labor_amount(None, None), 0.0)

    def test_unreadable_clock_is_zero(self):
        self.assertEqual(clock_hours('下午', '16:58'), 0.0)
        self.assertEqual(clock_hours('', '16:58'), 0.0)

    def test_hours_past_midnight(self):
        self.assertEqual(clock_hours('22:00', '25:00'), 3.0)
