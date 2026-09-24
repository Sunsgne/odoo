"""Free-text matching for the homepage search box.

Any non-empty keyword is a valid query. Callers must not reject text that is
not an IP address or a CIDR.
"""

PER_MODEL = 6
TOTAL = 36

SOURCES = (
    {
        'model': 'res.partner',
        'kind': '联系人',
        'fields': ('name', 'email', 'phone', 'vat', 'city', 'street', 'ref', 'zenlenet_code'),
        'reads': ('name', 'customer_rank', 'supplier_rank'),
        'label': 'name',
        'order': 'name',
    },
    {
        'model': 'zenlenet.prefix',
        'kind': '地址段',
        'fields': ('prefix', 'description', 'role', 'region', 'vlan', 'partner_id.name'),
        'reads': ('prefix',),
        'label': 'prefix',
        'order': 'prefix',
    },
    {
        'model': 'zenlenet.address',
        'kind': '地址',
        'fields': ('address', 'block', 'usage', 'remark', 'pop', 'partner_id.name'),
        'reads': ('address',),
        'label': 'address',
        'order': 'address',
    },
    {
        'model': 'zenlenet.line',
        'kind': '线路',
        'fields': ('name', 'a_end', 'z_end', 'purpose', 'bandwidth', 'partner_name', 'partner_id.name'),
        'reads': ('name',),
        'label': 'name',
        'order': 'name',
    },
    {
        'model': 'zenlenet.flow',
        'kind': '资源工单',
        'fields': ('name', 'reason', 'place', 'partner_id.name'),
        'reads': ('name',),
        'label': 'name',
        'order': 'id desc',
    },
    {
        'model': 'zenlenet.ticket',
        'kind': '服务工单',
        'fields': ('name', 'subject', 'contact', 'partner_id.name'),
        'reads': ('name', 'subject'),
        'label': 'name',
        'order': 'id desc',
    },
    {
        'model': 'zenlenet.contract',
        'kind': '合同',
        'fields': ('name', 'title', 'partner_id.name'),
        'reads': ('name',),
        'label': 'name',
        'order': 'id desc',
    },
    {
        'model': 'sale.order',
        'kind': '订单',
        'fields': ('name', 'client_order_ref', 'partner_id.name'),
        'reads': ('name', 'state'),
        'label': 'name',
        'order': 'id desc',
    },
    {
        'model': 'zenlenet.datacenter',
        'kind': '数据中心',
        'fields': ('name', 'city', 'code', 'region', 'address'),
        'reads': ('name',),
        'label': 'name',
        'order': 'name',
    },
    {
        'model': 'zenlenet.purchase',
        'kind': '采购',
        'fields': ('name', 'resource'),
        'reads': ('name',),
        'label': 'name',
        'order': 'id desc',
    },
    {
        'model': 'zenlenet.asset',
        'kind': '资产',
        'fields': ('name', 'serial', 'pop', 'code'),
        'reads': ('name',),
        'label': 'name',
        'order': 'name',
    },
    {
        'model': 'zenlenet.device',
        'kind': '物理机',
        'fields': ('name', 'serial', 'role'),
        'reads': ('name',),
        'label': 'name',
        'order': 'name',
    },
    {
        'model': 'zenlenet.vm',
        'kind': '云主机',
        'fields': ('name', 'ip_text', 'partner_id.name'),
        'reads': ('name',),
        'label': 'name',
        'order': 'name',
    },
    {
        'model': 'zenlenet.maintenance',
        'kind': '维护通告',
        'fields': ('name', 'place', 'reason', 'impact'),
        'reads': ('name',),
        'label': 'name',
        'order': 'id desc',
    },
)


def ilike_domain(term, fields):
    """Prefix-notation OR domain. A blank term matches nothing."""
    text = (term or '').strip()
    names = [name for name in fields if name]
    if not text or not names:
        return []
    leaves = [(name, 'ilike', text) for name in names]
    if len(leaves) == 1:
        return leaves
    return ['|'] * (len(leaves) - 1) + leaves


def row_kind(source, row):
    if source['model'] == 'res.partner':
        if row.get('customer_rank'):
            return '客户'
        if row.get('supplier_rank'):
            return '供应商'
        return '联系人'
    if source['model'] == 'sale.order' and row.get('state') in ('draft', 'sent'):
        return '报价'
    return source['kind']


def row_label(source, row):
    if source['model'] == 'zenlenet.ticket':
        name = row.get('name') or ''
        subject = row.get('subject') or ''
        if subject and name and subject != name:
            return f'{name} {subject}'
        return subject or name
    return row.get(source['label']) or ''
