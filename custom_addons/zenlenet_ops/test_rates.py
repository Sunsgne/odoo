import unittest

from rates import parse_ecb, parse_frankfurter, rates_per_company


class RateConversionTests(unittest.TestCase):
    def test_eur_pivot_to_usd(self):
        table = rates_per_company(
            {'EUR': 1.0, 'USD': 1.1, 'CNY': 7.7, 'SGD': 1.43},
            'EUR',
            'USD',
        )
        self.assertEqual(table['USD'], 1.0)
        self.assertAlmostEqual(table['CNY'], 7.0)
        self.assertAlmostEqual(table['EUR'], 1 / 1.1)
        self.assertAlmostEqual(table['SGD'], 1.43 / 1.1)

    def test_company_currency_is_the_base(self):
        table = rates_per_company({'CNY': 6.7074, 'EUR': 0.87635}, 'USD', 'USD')
        self.assertEqual(table['USD'], 1.0)
        self.assertAlmostEqual(table['CNY'], 6.7074)

    def test_missing_company_currency(self):
        with self.assertRaises(ValueError):
            rates_per_company({'EUR': 1.0, 'USD': 1.1}, 'EUR', 'SGD')

    def test_zero_pivot(self):
        with self.assertRaises(ValueError):
            rates_per_company({'EUR': 1.0, 'USD': 0}, 'EUR', 'USD')

    def test_frankfurter_sample(self):
        payload = (
            '{"amount":1.0,"base":"USD","date":"2026-09-23","rates":'
            '{"AUD":1.415,"CAD":1.4089,"CHF":0.82289,"CNY":6.7074,"EUR":0.87635,'
            '"GBP":0.75322,"HKD":7.8438,"JPY":157.92,"SGD":1.2783}}'
        )
        table, day = parse_frankfurter(payload, 'USD')
        self.assertEqual(day, '2026-09-23')
        self.assertEqual(table['USD'], 1.0)
        self.assertAlmostEqual(table['JPY'], 157.92)
        self.assertAlmostEqual(table['CNY'], 6.7074)

    def test_frankfurter_rejects_a_bad_date(self):
        with self.assertRaises(ValueError):
            parse_frankfurter('{"base":"USD","date":"yesterday","rates":{"EUR":0.8}}', 'USD')

    def test_ecb_sample(self):
        payload = '''<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
<Cube><Cube time="2026-09-23">
<Cube currency="USD" rate="1.10"/>
<Cube currency="CNY" rate="7.70"/>
</Cube></Cube>
</gesmes:Envelope>'''
        table, day = parse_ecb(payload, 'USD')
        self.assertEqual(day, '2026-09-23')
        self.assertEqual(table['USD'], 1.0)
        self.assertAlmostEqual(table['CNY'], 7.0)
        self.assertAlmostEqual(table['EUR'], 1 / 1.1)


if __name__ == '__main__':
    unittest.main()
