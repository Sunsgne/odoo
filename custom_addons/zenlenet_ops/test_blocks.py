import unittest

from blocks import prefix_block


class PrefixBlockTests(unittest.TestCase):
    def test_host_rolls_up_to_24(self):
        self.assertEqual(prefix_block(4, '193.239.155.8', 32), '193.239.155.0/24')

    def test_v6_keeps_its_prefix(self):
        self.assertEqual(prefix_block(6, '2001:db8::1', 64), '2001:db8::/64')

    def test_bad_text_is_kept(self):
        self.assertEqual(prefix_block(4, 'not-an-ip', 32), 'not-an-ip/32')


if __name__ == '__main__':
    unittest.main()
