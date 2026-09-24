import unittest

from blocks import edge_label, parse_prefix, prefix_block


class PrefixBlockTests(unittest.TestCase):
    def test_host_rolls_up_to_24(self):
        self.assertEqual(prefix_block(4, '193.239.155.8', 32), '193.239.155.0/24')

    def test_v6_keeps_its_prefix(self):
        self.assertEqual(prefix_block(6, '2001:db8::1', 64), '2001:db8::/64')

    def test_bad_text_is_kept(self):
        self.assertEqual(prefix_block(4, 'not-an-ip', 32), 'not-an-ip/32')

    def test_prefix_drops_host_bits(self):
        self.assertEqual(parse_prefix('192.0.2.9/24'), '192.0.2.0/24')
        self.assertEqual(parse_prefix('2001:db8::1/64'), '2001:db8::/64')

    def test_prefix_rejects_blank(self):
        with self.assertRaises(ValueError):
            parse_prefix('  ')

    def test_slash24_ends_cannot_be_allocated(self):
        self.assertEqual(edge_label('128.14.5.0/24', '128.14.5.0'), '网络位')
        self.assertEqual(edge_label('128.14.5.0/24', '128.14.5.255'), '广播位')
        self.assertEqual(edge_label('128.14.5.0/24', '128.14.5.1'), '')

    def test_only_the_parent_ends_are_blocked(self):
        self.assertEqual(edge_label('10.0.0.0/23', '10.0.0.0'), '网络位')
        self.assertEqual(edge_label('10.0.0.0/23', '10.0.0.255'), '')
        self.assertEqual(edge_label('10.0.0.0/23', '10.0.1.255'), '广播位')

    def test_point_to_point_ends_stay_usable(self):
        self.assertEqual(edge_label('192.0.2.0/31', '192.0.2.0'), '')
        self.assertEqual(edge_label('192.0.2.1/32', '192.0.2.1'), '')


if __name__ == '__main__':
    unittest.main()
