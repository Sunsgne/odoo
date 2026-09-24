import unittest

from blocks import allocation_rows, compact_hosts, parse_prefix, prefix_block


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

    def test_slash24_hosts_collapse_to_last_octet(self):
        text = compact_hosts(['124.254.90.8', '124.254.90.2', '124.254.90.3', '124.254.90.4', '124.254.90.10'], '124.254.90.0/24')
        self.assertEqual(text, '.2–.4 .8 .10')

    def test_larger_prefix_keeps_full_addresses(self):
        text = compact_hosts(['10.0.0.1', '10.0.0.2', '10.0.1.1'], '10.0.0.0/23')
        self.assertEqual(text, '10.0.0.1–10.0.0.2 10.0.1.1')

    def test_allocation_rows_group_customers(self):
        rows = allocation_rows('124.254.90.0/24', [
            {'ip': '124.254.90.2', 'status': 'allocated', 'partner': '甲'},
            {'ip': '124.254.90.3', 'status': 'allocated', 'partner': '甲'},
            {'ip': '124.254.90.9', 'status': 'reserved', 'partner': '乙'},
            {'ip': '124.254.90.1', 'status': 'free', 'partner': ''},
            {'ip': '124.254.90.4', 'status': 'internal', 'partner': ''},
        ], {'allocated': '已分配', 'reserved': '预分配', 'internal': '自用'})
        self.assertEqual([(row['partner'], row['status_label'], row['count'], row['hosts']) for row in rows], [
            ('甲', '已分配', 2, '.2–.3'),
            ('乙', '预分配', 1, '.9'),
            ('自用', '自用', 1, '.4'),
        ])


if __name__ == '__main__':
    unittest.main()
