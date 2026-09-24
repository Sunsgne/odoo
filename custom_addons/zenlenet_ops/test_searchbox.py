import unittest

from searchbox import ilike_domain, row_kind, row_label


class SearchboxTests(unittest.TestCase):
    def test_blank_matches_nothing(self):
        self.assertEqual(ilike_domain('   ', ['name']), [])
        self.assertEqual(ilike_domain('', ['name']), [])
        self.assertEqual(ilike_domain('x', []), [])

    def test_one_field(self):
        self.assertEqual(ilike_domain('abc', ['name']), [('name', 'ilike', 'abc')])

    def test_or_prefix(self):
        self.assertEqual(
            ilike_domain('1.2', ['address', 'block']),
            ['|', ('address', 'ilike', '1.2'), ('block', 'ilike', '1.2')],
        )

    def test_any_keyword_is_a_query(self):
        domain = ilike_domain('不是地址', ['address', 'usage', 'partner_id.name'])
        self.assertEqual(domain[:2], ['|', '|'])
        self.assertIn(('address', 'ilike', '不是地址'), domain)
        self.assertIn(('usage', 'ilike', '不是地址'), domain)
        self.assertIn(('partner_id.name', 'ilike', '不是地址'), domain)

    def test_partner_kind(self):
        partner = {'model': 'res.partner', 'kind': '联系人'}
        self.assertEqual(row_kind(partner, {'customer_rank': 1, 'supplier_rank': 0}), '客户')
        self.assertEqual(row_kind(partner, {'customer_rank': 0, 'supplier_rank': 2}), '供应商')
        self.assertEqual(row_kind(partner, {'customer_rank': 1, 'supplier_rank': 2}), '客户')
        self.assertEqual(row_kind(partner, {}), '联系人')

    def test_quote_versus_order(self):
        source = {'model': 'sale.order', 'kind': '订单'}
        self.assertEqual(row_kind(source, {'state': 'draft'}), '报价')
        self.assertEqual(row_kind(source, {'state': 'sent'}), '报价')
        self.assertEqual(row_kind(source, {'state': 'sale'}), '订单')

    def test_ticket_label_joins_subject(self):
        source = {'model': 'zenlenet.ticket', 'label': 'name'}
        self.assertEqual(row_label(source, {'name': 'T1', 'subject': '断线'}), 'T1 断线')
        self.assertEqual(row_label(source, {'name': '断线', 'subject': '断线'}), '断线')
        self.assertEqual(row_label(source, {'name': 'T1', 'subject': ''}), 'T1')
