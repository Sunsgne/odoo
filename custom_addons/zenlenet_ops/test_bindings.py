"""Resource bindings follow NetBox, not free text."""

import unittest

from resource_bindings import binding_text, circuit_kind, end_facts, mbps_of, site_line_domain, split_end, vlan_vid


class BindingTests(unittest.TestCase):
    def test_imported_end_keeps_the_vlan(self):
        self.assertEqual(split_end('香港二 200'), ('香港二', 200))
        self.assertEqual(split_end('仅机房'), ('仅机房', 0))
        self.assertEqual(vlan_vid('200'), 200)
        self.assertEqual(vlan_vid(''), 0)

    def test_circuit_types(self):
        self.assertEqual(circuit_kind('专线'), 'pl')
        self.assertEqual(circuit_kind('VXLAN'), 'vxlan')
        self.assertEqual(circuit_kind('SD-WAN'), 'sdwan')
        self.assertEqual(circuit_kind('SDWAN'), 'sdwan')
        self.assertEqual(circuit_kind('波分'), 'private')

    def test_bandwidth_prefers_the_commit(self):
        self.assertEqual(mbps_of('10M', 100), 100)
        self.assertEqual(mbps_of('450M', 0), 450)
        self.assertEqual(mbps_of('', 0), 0)

    def test_private_line_reads_as_device_port_vlan(self):
        self.assertEqual(binding_text('香港', 'sw1', 'Gi0/1', '200'), '香港 · sw1 · Gi0/1 · VLAN 200')
        self.assertEqual(binding_text('香港', '', '', ''), '香港')

    def test_netbox_termination_is_site_plus_cabled_interface(self):
        facts = end_facts({
            'id': 9,
            'termination_type': 'dcim.site',
            'termination': {'id': 3, 'name': '香港'},
            'port_speed': 100000,
            'link_peers': [{
                'id': 15,
                'name': 'Gi0/1',
                'device': {'id': 8, 'name': 'sw1'},
                'untagged_vlan': {'vid': 200},
            }],
        })
        self.assertEqual(facts['site_netbox_id'], 3)
        self.assertEqual(facts['device_name'], 'sw1')
        self.assertEqual(facts['port'], 'Gi0/1')
        self.assertEqual(facts['vlan'], '200')
        self.assertEqual(facts['port_mbps'], 100)

    def test_site_domain_has_one_operator_fewer_than_leaves(self):
        bare = site_line_domain(7, '')
        self.assertEqual(bare[:2], ['|', '|'])
        self.assertEqual(len([item for item in bare if item == '|']), 2)
        self.assertEqual(bare[2][0], 'datacenter_id')
        with_region = site_line_domain(7, '亚太')
        self.assertEqual(len([item for item in with_region if item == '|']), 3)
        self.assertEqual(with_region[-1], ('region', '=', '亚太'))

    def test_sdwan_termination_is_a_region(self):
        facts = end_facts({
            'id': 4,
            'termination_type': 'dcim.region',
            'termination': {'id': 2, 'name': '亚太'},
        })
        self.assertEqual(facts['region'], '亚太')
        self.assertEqual(facts['region_netbox_id'], 2)
        self.assertNotIn('device_name', facts)


if __name__ == '__main__':
    unittest.main()
