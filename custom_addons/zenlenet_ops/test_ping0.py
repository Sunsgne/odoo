import unittest

from ping0 import auth_failed, block24_of, labels, slash24s


class Ping0Tests(unittest.TestCase):
    def test_slash24_is_itself(self):
        self.assertEqual([str(item) for item in slash24s('10.88.120.0/24')], ['10.88.120.0/24'])

    def test_smaller_prefix_rolls_up(self):
        self.assertEqual([str(item) for item in slash24s('10.88.120.8/32')], ['10.88.120.0/24'])

    def test_slash22_splits(self):
        self.assertEqual(
            [str(item) for item in slash24s('10.88.120.0/22')],
            ['10.88.120.0/24', '10.88.121.0/24', '10.88.122.0/24', '10.88.123.0/24'],
        )

    def test_huge_container_is_not_exploded(self):
        self.assertEqual(slash24s('10.0.0.0/8'), [])

    def test_address_block(self):
        self.assertEqual(block24_of('10.88.120.194/32'), '10.88.120.0/24')
        self.assertEqual(block24_of(''), '')

    def test_labels(self):
        parsed = labels({
            'isidc': False,
            'isnative': False,
            'iprisk': 13,
            'location': '日本 东京都',
            'asn': 'AS2914',
        })
        self.assertEqual(parsed['ip_type'], '家庭宽带 IP')
        self.assertEqual(parsed['ip_native'], '广播 IP')
        self.assertEqual(parsed['ip_risk'], 13)

    def test_idc_native(self):
        parsed = labels({'isidc': True, 'isnative': True, 'iprisk': 0})
        self.assertEqual(parsed['ip_type'], 'IDC机房 IP')
        self.assertEqual(parsed['ip_native'], '原生 IP')
        self.assertEqual(parsed['ip_risk'], 0)

    def test_error_payload(self):
        self.assertIsNone(labels({'error': 'token not found'}))
        self.assertTrue(auth_failed(200, {'error': 'token not found'}))
        self.assertFalse(auth_failed(200, {'isidc': False, 'isnative': True}))


if __name__ == '__main__':
    unittest.main()
