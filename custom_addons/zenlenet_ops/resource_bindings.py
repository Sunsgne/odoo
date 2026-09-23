"""How a VM, an SD-WAN access and a private line attach to NetBox objects.

NetBox already keeps these as relations, not as loose text:

- a virtual machine sits on a site and a device, and its primary address is an IP
- an SD-WAN circuit terminates on a region and carries a commit rate
- a private line terminates on both ends; each end is cabled to a device interface,
  and that interface carries the VLAN
"""

import re


def split_end(text):
    """Split an imported 'place vlan' label into the place and the VLAN id."""
    parts = (text or '').split()
    if len(parts) >= 2 and parts[-1].isdigit():
        return ' '.join(parts[:-1]), int(parts[-1])
    return (text or '').strip(), 0


def circuit_kind(type_name):
    """Map a NetBox circuit type onto 专线 / SD-WAN / VXLAN / 其他."""
    raw = (type_name or '').strip()
    name = raw.lower().replace('_', '-').replace(' ', '')
    if name == 'vxlan':
        return 'vxlan'
    if name in ('sdwan', 'sd-wan') or ('sd' in name and 'wan' in name):
        return 'sdwan'
    if '专线' in raw or name in ('iepl', 'epl', 'dwdm', 'wavelength'):
        return 'pl'
    return 'private'


def mbps_of(bandwidth, commit_rate):
    """Prefer the numeric commit rate. Fall back to a label like ``100M``."""
    if commit_rate:
        return int(commit_rate)
    match = re.fullmatch(r'(\d+(?:\.\d+)?)M', (bandwidth or '').strip(), flags=re.IGNORECASE)
    if not match:
        return 0
    return int(float(match.group(1)))


def vlan_vid(text):
    text = (text or '').strip()
    return int(text) if text.isdigit() else 0


def kbps(mbps):
    return int(mbps) * 1000 if mbps else None


def site_line_domain(site_id, region):
    """Lines that belong on this site: either end, the site itself, or the same region.

    Prefix notation needs one ``|`` fewer than the number of leaves. An extra
    operator makes Odoo reject the domain and the site page fails to open.
    """
    leaves = [
        ('datacenter_id', '=', site_id),
        ('a_site_id', '=', site_id),
        ('z_site_id', '=', site_id),
    ]
    if region:
        leaves.append(('region', '=', region))
    return ['|'] * (len(leaves) - 1) + leaves


def binding_text(site, device, port, vlan):
    """One line an operator can read: site, device, port, VLAN."""
    bits = [bit for bit in (site or '', device or '', port or '') if bit]
    vid = vlan_vid(vlan) if not isinstance(vlan, int) else vlan
    if vid:
        bits.append(f'VLAN {vid}')
    return ' · '.join(bits)


def end_facts(term):
    """Read one NetBox circuit termination into the fields the console stores.

    A termination hangs off a site, a region or a provider network. The device
    and port are the interface that termination is cabled to. VLAN lives on
    that interface, so it is filled in by the caller when the interface payload
    actually includes it.
    """
    if not term:
        return {}
    inner = term.get('termination') or {}
    kind = term.get('termination_type') or ''
    facts = {'term_netbox_id': term.get('id') or 0}
    if kind == 'dcim.site':
        facts['site_netbox_id'] = inner.get('id') or 0
        facts['site_name'] = inner.get('name') or inner.get('display') or ''
    elif kind == 'dcim.region':
        facts['region'] = inner.get('name') or inner.get('display') or ''
        facts['region_netbox_id'] = inner.get('id') or 0
    elif kind == 'dcim.location':
        site = inner.get('site') or {}
        facts['site_netbox_id'] = site.get('id') or 0
        facts['site_name'] = site.get('name') or inner.get('display') or ''
    peers = term.get('link_peers') or []
    if peers:
        peer = peers[0]
        device = peer.get('device') or {}
        facts['iface_netbox_id'] = peer.get('id') or 0
        facts['port'] = peer.get('name') or ''
        facts['device_netbox_id'] = device.get('id') or 0
        facts['device_name'] = device.get('name') or device.get('display') or ''
        vlan = peer.get('untagged_vlan') or {}
        if isinstance(vlan, dict) and vlan.get('vid'):
            facts['vlan'] = str(vlan['vid'])
    speed = term.get('port_speed') or 0
    if speed:
        facts['port_mbps'] = int(speed / 1000) if speed >= 1000 else speed
    return facts
