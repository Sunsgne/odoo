import unittest

from blocks import parse_prefix, prefix_block


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


if __name__ == '__main__':
    unittest.main()
