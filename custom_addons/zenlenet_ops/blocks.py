"""IP block labels shared by the address import. No Odoo imports."""

import ipaddress


def prefix_block(version, address, prefixlen):
    text = f'{address}/{prefixlen}'
    try:
        network = ipaddress.ip_network(text, strict=False)
    except ValueError:
        return text
    if network.version == 4 and int(prefixlen or 32) == 32:
        return str(ipaddress.ip_network(f'{network.network_address}/24', strict=False))
    return str(network)


def parse_prefix(text):
    network = ipaddress.ip_network(str(text or '').strip(), strict=False)
    return str(network)


def edge_label(prefix, ip):
    """'网络位' or '广播位' when this host is an end that cannot be given to a customer.

    /31 and /32, and the IPv6 equivalents, have no reserved ends.
    """
    try:
        network = ipaddress.ip_network(str(prefix or '').strip(), strict=False)
        host = ipaddress.ip_address(str(ip or '').split('/')[0].strip())
    except ValueError:
        return ''
    if host not in network:
        return ''
    if network.version == 4 and network.prefixlen >= 31:
        return ''
    if network.version == 6 and network.prefixlen >= 127:
        return ''
    if host == network.network_address:
        return '网络位'
    if host == network.broadcast_address:
        return '广播位'
    return ''


HELD_STATUSES = ('allocated', 'reserved', 'testing', 'transferring', 'returning', 'internal')


def compact_hosts(ips, prefix=''):
    """Turn host addresses into ranges written as full addresses, same shape as the block title."""
    hosts = []
    for ip in ips or []:
        try:
            hosts.append(ipaddress.ip_address(str(ip).split('/')[0]))
        except ValueError:
            continue
    hosts = sorted(set(hosts), key=int)
    if not hosts:
        return ''

    def piece(start, end):
        if start == end:
            return str(start)
        return f'{start} – {end}'

    parts = []
    start = prev = hosts[0]
    for host in hosts[1:]:
        if int(host) == int(prev) + 1:
            prev = host
            continue
        parts.append(piece(start, prev))
        start = prev = host
    parts.append(piece(start, prev))
    return '、'.join(parts)


def allocation_rows(prefix, hosts, labels=None):
    """Group assigned addresses by customer and status so the grid can be read at a glance."""
    labels = labels or {}
    order = {status: index for index, status in enumerate(HELD_STATUSES)}
    groups = {}
    for item in hosts or []:
        status = item.get('status') or ''
        if status not in order:
            continue
        partner = (item.get('partner') or '').strip()
        if status == 'internal' and not partner:
            partner = '自用'
        elif not partner:
            partner = '未填写'
        groups.setdefault((partner, status), []).append(item.get('ip') or '')
    rows = []
    for (partner, status), ips in groups.items():
        rows.append({
            'partner': partner,
            'status': status,
            'status_label': labels.get(status, status),
            'count': len(ips),
            'hosts': compact_hosts(ips, prefix),
        })
    rows.sort(key=lambda row: (order.get(row['status'], 9), -row['count'], row['partner']))
    return rows
