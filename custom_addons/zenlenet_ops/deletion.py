"""Delete policy for console records.

Only 运营主管 may delete business records, and only while the record has not yet produced anything
other people depend on (invoices, allocated resources, audit history). Every rule works on a plain
snapshot dict so it can be unit tested without an Odoo registry.
"""

MANAGER_ONLY = '只有「运营主管」可以删除记录。其他岗位请用取消 / 终止 / 释放代替删除。'


def _contract(snap):
    if snap.get('invoice_count'):
        return '合同已出过账单，不能删除；请改为「终止」。'
    if snap.get('state') != 'draft':
        return '只有草稿合同可以删除，已生效的合同请「终止」。'
    return None


def _contract_item(snap):
    if snap.get('contract_state') != 'draft':
        return '合同已生效，费用项不能删除；请新增调整项或终止合同。'
    return None


def _flow(snap):
    if snap.get('state') not in ('company', 'cancel'):
        return '交付工单已进入流转，只能「取消」，不能删除。'
    if snap.get('allocated'):
        return '工单上还挂着已分配的资源，请先释放。'
    return None


def _flow_task(snap):
    if snap.get('flow_state') == 'done':
        return '已完成的交付工单，任务记录不可删除。'
    if snap.get('state') == 'done':
        return '已完成的任务不可删除，请改为「跳过」或重新打开。'
    return None


def _flow_resource(snap):
    if snap.get('flow_state') == 'done':
        return '已完成的交付工单，资源记录不可删除；请通过回收工单释放。'
    if snap.get('assigned') and snap.get('flow_state') not in ('company', 'allocate', 'cancel'):
        return '资源已交付，请通过工单「回收」释放，而不是删除。'
    return None


def _ticket(snap):
    if snap.get('state') not in ('new', 'cancel'):
        return '工单已开始处理，请「关闭」或「取消」，不要删除。'
    return None


def _prefix(snap):
    if snap.get('child_count'):
        return '网段下还有子网段，请先删除子网段。'
    if snap.get('used_addresses'):
        return '网段下有已分配 / 预留 / 自用的地址，请先释放。'
    if snap.get('status') == 'active' and snap.get('partner'):
        return '网段已分配给客户，请先「释放」。'
    return None


def _address(snap):
    if snap.get('status') != 'free':
        return '只有「未分配」的地址可以删除，请先释放。'
    return None


def _line(snap):
    if snap.get('status') in ('provisioning', 'active', 'deprovisioning'):
        return '线路在用或正在开通 / 拆除，请先改为「已终止」。'
    if snap.get('partner') and snap.get('status') != 'decommissioned':
        return '线路仍挂在客户名下，请先终止。'
    return None


def _datacenter(snap):
    for key, label in (('prefix_count', '网段'), ('address_count', '地址'), ('line_count', '线路'), ('asset_count', '设备')):
        if snap.get(key):
            return f'数据中心下还有 {label}，不能删除；可改为「已退租」。'
    return None


def _purchase(snap):
    if snap.get('bill_count'):
        return '采购已生成供应商账单，不能删除。'
    if snap.get('state') != 'draft':
        return '只有「待采购」的采购单可以删除。'
    return None


def _asset(snap):
    if snap.get('state') == 'in_use':
        return '在用设备不能删除，请先改为「闲置」或「报废」。'
    return None


def _credit(snap):
    if snap.get('state') in ('approved', 'applied'):
        return '已批准 / 已抵扣的减免不能删除。'
    return None


def _maintenance(snap):
    if snap.get('state') not in ('draft', 'cancel'):
        return '维护通告已进入评审或已通知客户，请「取消」，不要删除。'
    return None


RULES = {
    'zenlenet.contract': _contract,
    'zenlenet.contract.item': _contract_item,
    'zenlenet.flow': _flow,
    'zenlenet.flow.task': _flow_task,
    'zenlenet.flow.resource': _flow_resource,
    'zenlenet.ticket': _ticket,
    'zenlenet.prefix': _prefix,
    'zenlenet.address': _address,
    'zenlenet.line': _line,
    'zenlenet.datacenter': _datacenter,
    'zenlenet.purchase': _purchase,
    'zenlenet.asset': _asset,
    'zenlenet.credit': _credit,
    'zenlenet.maintenance': _maintenance,
}

# Line items the owning role may delete itself (still subject to the state rules above).
ROLE_DELETABLE = {'zenlenet.contract.item', 'zenlenet.flow.task', 'zenlenet.flow.resource'}

def blocked_reason(model, snap):
    """Return a Chinese explanation when the record must not be deleted, otherwise None."""
    rule = RULES.get(model)
    return rule(snap) if rule else None


def can_delete(model, snap, is_manager, in_role=False):
    if not is_manager and not (in_role and model in ROLE_DELETABLE):
        return MANAGER_ONLY
    return blocked_reason(model, snap)
