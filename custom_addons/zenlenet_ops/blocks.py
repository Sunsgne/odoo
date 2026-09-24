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
