import unittest

from deletion import MANAGER_ONLY, RULES, blocked_reason, can_delete


class DeletePolicyTests(unittest.TestCase):
    def test_non_manager_cannot_delete_business_records(self):
        self.assertEqual(can_delete('zenlenet.contract', {'state': 'draft'}, is_manager=False), MANAGER_ONLY)
        self.assertEqual(can_delete('zenlenet.ticket', {'state': 'new'}, is_manager=False, in_role=True), MANAGER_ONLY)

    def test_role_may_delete_own_line_items(self):
        self.assertIsNone(can_delete('zenlenet.contract.item', {'contract_state': 'draft'}, False, in_role=True))
        self.assertIsNone(can_delete('zenlenet.flow.task', {'state': 'todo', 'flow_state': 'deliver'}, False, in_role=True))

    def test_manager_still_bound_by_state(self):
        self.assertIsNotNone(can_delete('zenlenet.contract', {'state': 'active'}, is_manager=True))
        self.assertIsNone(can_delete('zenlenet.contract', {'state': 'draft', 'invoice_count': 0}, is_manager=True))

    def test_contract(self):
        self.assertIsNone(blocked_reason('zenlenet.contract', {'state': 'draft', 'invoice_count': 0}))
        self.assertIn('账单', blocked_reason('zenlenet.contract', {'state': 'draft', 'invoice_count': 2}))
        self.assertIn('终止', blocked_reason('zenlenet.contract', {'state': 'active', 'invoice_count': 0}))
        self.assertIn('生效', blocked_reason('zenlenet.contract.item', {'contract_state': 'active'}))

    def test_flow(self):
        self.assertIsNone(blocked_reason('zenlenet.flow', {'state': 'company', 'allocated': False}))
        self.assertIsNone(blocked_reason('zenlenet.flow', {'state': 'cancel', 'allocated': False}))
        self.assertIn('取消', blocked_reason('zenlenet.flow', {'state': 'deliver', 'allocated': False}))
        self.assertIn('释放', blocked_reason('zenlenet.flow', {'state': 'company', 'allocated': True}))
        self.assertIsNotNone(blocked_reason('zenlenet.flow.task', {'state': 'done', 'flow_state': 'deliver'}))
        self.assertIsNotNone(blocked_reason('zenlenet.flow.task', {'state': 'todo', 'flow_state': 'done'}))
        self.assertIsNone(blocked_reason('zenlenet.flow.resource', {'assigned': True, 'flow_state': 'allocate'}))
        self.assertIn('回收', blocked_reason('zenlenet.flow.resource', {'assigned': True, 'flow_state': 'deliver'}))

    def test_ticket(self):
        self.assertIsNone(blocked_reason('zenlenet.ticket', {'state': 'new'}))
        self.assertIsNone(blocked_reason('zenlenet.ticket', {'state': 'cancel'}))
        self.assertIsNotNone(blocked_reason('zenlenet.ticket', {'state': 'processing'}))
        self.assertIsNotNone(blocked_reason('zenlenet.ticket', {'state': 'closed'}))

    def test_ipam(self):
        free = {'status': 'active', 'child_count': 0, 'used_addresses': 0, 'partner': False}
        self.assertIsNone(blocked_reason('zenlenet.prefix', free))
        self.assertIn('子网段', blocked_reason('zenlenet.prefix', dict(free, child_count=2)))
        self.assertIn('地址', blocked_reason('zenlenet.prefix', dict(free, used_addresses=5)))
        self.assertIn('释放', blocked_reason('zenlenet.prefix', dict(free, partner=True)))
        self.assertIsNone(blocked_reason('zenlenet.address', {'status': 'free'}))
        for status in ('allocated', 'reserved', 'internal', 'testing', 'returning'):
            self.assertIsNotNone(blocked_reason('zenlenet.address', {'status': status}), status)

    def test_device_and_vm(self):
        self.assertIsNone(blocked_reason('zenlenet.device', {'vm_count': 0}))
        self.assertIn('云主机', blocked_reason('zenlenet.device', {'vm_count': 2}))
        self.assertIsNone(blocked_reason('zenlenet.vm', {'status': 'offline', 'partner': True}))
        self.assertIn('客户', blocked_reason('zenlenet.vm', {'status': 'active', 'partner': True}))

    def test_line_and_datacenter(self):
        self.assertIsNone(blocked_reason('zenlenet.line', {'status': 'decommissioned', 'partner': True}))
        self.assertIsNone(blocked_reason('zenlenet.line', {'status': 'planned', 'partner': False}))
        self.assertIsNotNone(blocked_reason('zenlenet.line', {'status': 'active', 'partner': False}))
        self.assertIsNotNone(blocked_reason('zenlenet.line', {'status': 'planned', 'partner': True}))
        empty = {'prefix_count': 0, 'address_count': 0, 'line_count': 0, 'asset_count': 0}
        self.assertIsNone(blocked_reason('zenlenet.datacenter', empty))
        self.assertIn('线路', blocked_reason('zenlenet.datacenter', dict(empty, line_count=3)))

    def test_purchasing_and_misc(self):
        self.assertIsNone(blocked_reason('zenlenet.purchase', {'state': 'draft', 'bill_count': 0}))
        self.assertIsNotNone(blocked_reason('zenlenet.purchase', {'state': 'ordered', 'bill_count': 0}))
        self.assertIsNotNone(blocked_reason('zenlenet.purchase', {'state': 'draft', 'bill_count': 1}))
        self.assertIsNone(blocked_reason('zenlenet.asset', {'state': 'idle'}))
        self.assertIsNotNone(blocked_reason('zenlenet.asset', {'state': 'in_use'}))
        self.assertIsNone(blocked_reason('zenlenet.credit', {'state': 'rejected'}))
        self.assertIsNotNone(blocked_reason('zenlenet.credit', {'state': 'applied'}))
        self.assertIsNone(blocked_reason('zenlenet.maintenance', {'state': 'draft'}))
        self.assertIsNotNone(blocked_reason('zenlenet.maintenance', {'state': 'notified'}))

    def test_unknown_model_is_unrestricted(self):
        self.assertIsNone(blocked_reason('zenlenet.ipset', {}))

    def test_every_rule_handles_empty_snapshot(self):
        for model, rule in RULES.items():
            rule({})


if __name__ == '__main__':
    unittest.main()
