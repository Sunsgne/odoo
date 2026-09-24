"""Person-assigned handoff. No Odoo imports."""

# Which concrete resource a demand line may hold. Anything else (云主机、托管、转售) needs no network resource.
RESOURCE_SLOT = {
    'ipt': 'prefix',
    'ip': 'prefix',
    'ip_single': 'address',
    'pl': 'line',
    'sdwan': 'line',
    'line': 'line',
}


def resource_slot(service_type):
    return RESOURCE_SLOT.get(service_type)


def normalize_assignment(service_type, prefix_id=None, address_id=None, line_id=None, resource_ref=None):
    """A demand line holds exactly one resource, and only the kind its business uses.

    ``resource_ref`` (``model,id``) is accepted so older callers keep working. Returns
    ``(prefix_id, address_id, line_id)`` with the unused slots cleared.
    """
    if resource_ref and not any((prefix_id, address_id, line_id)):
        model, _, raw = str(resource_ref).partition(',')
        try:
            rid = int(raw)
        except (TypeError, ValueError):
            rid = None
        if model == 'zenlenet.prefix':
            prefix_id = rid
        elif model == 'zenlenet.address':
            address_id = rid
        elif model == 'zenlenet.line':
            line_id = rid
    slot = resource_slot(service_type)
    if slot == 'prefix':
        return prefix_id or None, None, None
    if slot == 'address':
        return None, address_id or None, None
    if slot == 'line':
        return None, None, line_id or None
    return None, None, None


def resource_reference(prefix_id, address_id, line_id):
    if prefix_id:
        return f'zenlenet.prefix,{prefix_id}'
    if address_id:
        return f'zenlenet.address,{address_id}'
    if line_id:
        return f'zenlenet.line,{line_id}'
    return False


STATES = [
    ('company', '录入客户'),
    ('allocate', '分配资源'),
    ('deliver', '交付'),
    ('accept', '验收'),
    ('decide', '测试结论'),
    ('reclaim', '回收'),
    ('done', '完成'),
    ('cancel', '已取消'),
]

MOVES = ('out', 'in', 'back', 'cutover')
BUSINESS = ('company', 'allocate', 'deliver', 'accept', 'done')
TEST = ('company', 'allocate', 'deliver', 'accept', 'decide', 'reclaim', 'done')
INBOUND = ('company', 'allocate', 'deliver', 'done')
RETURN = ('company', 'reclaim', 'done')
CUTOVER = ('company', 'deliver', 'allocate', 'accept', 'done')
CONVERT_FROM = ('accept', 'decide', 'reclaim')
RECLAIM_FROM = ('accept', 'decide')
STEP_LABELS = {
    'out': dict(STATES),
    'in': {
        'company': '登记来源', 'allocate': '核对资源', 'deliver': '确认入库',
        'done': '完成', 'cancel': '已取消',
    },
    'back': {
        'company': '登记退回', 'reclaim': '回收资源', 'done': '完成', 'cancel': '已取消',
    },
    'cutover': {
        'company': '割接方案', 'deliver': '通知客户', 'allocate': '更换资源',
        'accept': '业务验证', 'done': '完成', 'cancel': '已取消',
    },
}

# Outbound business tickets. One service, one path. Cloud products skip the network desk.
_NET = ('company', 'allocate', 'deliver', 'accept', 'done')
_CLOUD = ('company', 'deliver', 'accept', 'done')
TRACKS = {
    'ipt': {
        'path': _NET,
        'labels': {'company': '客户与 ASN', 'allocate': '端口与地址', 'deliver': 'BGP 开通', 'accept': '验收', 'done': '完成'},
        'teams': {'company': 'sales', 'allocate': 'allocator', 'deliver': 'delivery', 'accept': 'service', 'done': 'service'},
        'tasks': (
            ('allocate', '分配端口和地址段', 'allocator', 1),
            ('deliver', 'BGP 会话与路由宣告', 'delivery', 1),
            ('deliver', '接入 95 值监控', 'delivery', 0),
            ('accept', '客户验收', 'service', 2),
        ),
    },
    'ip': {
        'path': _NET,
        'labels': {'company': '客户确认', 'allocate': '划出地址段', 'deliver': '路由宣告', 'accept': '验收', 'done': '完成'},
        'teams': {'company': 'sales', 'allocate': 'allocator', 'deliver': 'delivery', 'accept': 'service', 'done': 'service'},
        'tasks': (
            ('allocate', '从地址池划出', 'allocator', 1),
            ('deliver', '路由宣告', 'delivery', 1),
            ('accept', '客户验收', 'service', 1),
        ),
    },
    'ip_single': {
        'path': _NET,
        'labels': {'company': '客户确认', 'allocate': '划出地址', 'deliver': '交付地址', 'accept': '验收', 'done': '完成'},
        'teams': {'company': 'sales', 'allocate': 'allocator', 'deliver': 'delivery', 'accept': 'service', 'done': 'service'},
        'tasks': (
            ('allocate', '从地址池划出', 'allocator', 1),
            ('deliver', '写入客户资料', 'delivery', 0),
            ('accept', '客户验收', 'service', 1),
        ),
    },
    'pl': {
        'path': _NET,
        'labels': {'company': '客户确认', 'allocate': '两端核查', 'deliver': '端口开通', 'accept': '时延验收', 'done': '完成'},
        'teams': {'company': 'sales', 'allocate': 'allocator', 'deliver': 'delivery', 'accept': 'service', 'done': 'service'},
        'tasks': (
            ('allocate', '核对两端资源', 'allocator', 1),
            ('deliver', '端口与 VLAN 开通', 'delivery', 2),
            ('deliver', '时延与丢包测试', 'delivery', 1),
            ('accept', '客户验收', 'service', 2),
        ),
    },
    'line': {
        'path': _NET,
        'labels': {'company': '客户确认', 'allocate': '两端核查', 'deliver': '线路开通', 'accept': '验收', 'done': '完成'},
        'teams': {'company': 'sales', 'allocate': 'allocator', 'deliver': 'delivery', 'accept': 'service', 'done': 'service'},
        'tasks': (
            ('allocate', '核对线路', 'allocator', 1),
            ('deliver', '线路开通', 'delivery', 2),
            ('accept', '客户验收', 'service', 1),
        ),
    },
    'sdwan': {
        'path': _NET,
        'labels': {'company': '客户确认', 'allocate': '站点与设备', 'deliver': '隧道策略', 'accept': '体验验收', 'done': '完成'},
        'teams': {'company': 'sales', 'allocate': 'allocator', 'deliver': 'delivery', 'accept': 'service', 'done': 'service'},
        'tasks': (
            ('allocate', '确认站点和设备', 'allocator', 1),
            ('deliver', 'CPE 上线', 'delivery', 3),
            ('deliver', '隧道与选路', 'delivery', 1),
            ('accept', '客户验收', 'service', 2),
        ),
    },
    'vm': {
        'path': _CLOUD,
        'labels': {'company': '规格确认', 'deliver': '开通实例', 'accept': '验收', 'done': '完成'},
        'teams': {'company': 'sales', 'deliver': 'delivery', 'accept': 'service', 'done': 'service'},
        'tasks': (
            ('deliver', '开通实例', 'delivery', 1),
            ('deliver', '交付登录账号', 'delivery', 0),
            ('accept', '客户验收', 'service', 1),
        ),
    },
    'colo': {
        'path': _NET,
        'labels': {'company': '客户确认', 'allocate': '机柜与电力', 'deliver': '上架加电', 'accept': '验收', 'done': '完成'},
        'teams': {'company': 'sales', 'allocate': 'allocator', 'deliver': 'delivery', 'accept': 'service', 'done': 'service'},
        'tasks': (
            ('allocate', '确认机柜和电力', 'allocator', 1),
            ('deliver', '上架与交叉连接', 'delivery', 3),
            ('accept', '加电验收', 'service', 1),
        ),
    },
    'resale': {
        'path': _NET,
        'labels': {'company': '客户确认', 'allocate': '供应商下单', 'deliver': '上游交付', 'accept': '转交客户', 'done': '完成'},
        'teams': {'company': 'sales', 'allocate': 'allocator', 'deliver': 'delivery', 'accept': 'service', 'done': 'service'},
        'tasks': (
            ('allocate', '向供应商下单', 'allocator', 1),
            ('deliver', '供应商交付', 'delivery', 3),
            ('accept', '转交客户', 'service', 1),
        ),
    },
}


def track_for(service):
    return TRACKS.get(service or '')


def path_for(move, kind, service=None):
    move = move or 'out'
    if move == 'in':
        return INBOUND
    if move == 'back':
        return RETURN
    if move == 'cutover':
        return CUTOVER
    if move == 'out' and kind != 'test':
        track = track_for(service)
        if track:
            return track['path']
    return TEST if kind == 'test' else BUSINESS


def next_state(kind, state, move='out', service=None):
    if (move or 'out') == 'out' and kind == 'test' and state in ('accept', 'decide'):
        return None
    path = path_for(move, kind, service)
    if state not in path:
        return None
    index = path.index(state)
    if index >= len(path) - 1:
        return None
    return path[index + 1]


def prev_state(kind, state, move='out', service=None):
    path = path_for(move, kind, service)
    if state not in path:
        return None
    index = path.index(state)
    if index == 0:
        return None
    return path[index - 1]


def can_convert(kind, state, move='out'):
    return (move or 'out') == 'out' and kind == 'test' and state in CONVERT_FROM


def can_reclaim(kind, state, move='out'):
    return (move or 'out') == 'out' and kind == 'test' and state in RECLAIM_FROM


def transition_allowed(kind, state, new_kind, new_state, move='out', new_move=None, service=None, new_service=None):
    move = move or 'out'
    new_move = new_move or move
    new_service = service if new_service is None else new_service
    if new_service != service:
        return state == 'company' and new_state == 'company' and new_kind == kind and new_move == move
    if new_move != move:
        return state == 'company' and new_state == 'company' and new_kind == kind
    if new_kind == kind and new_state == state:
        return True
    if state in ('done', 'cancel'):
        return False
    if new_state == 'cancel' and new_kind == kind:
        return True
    if move != 'out':
        if new_kind != kind:
            return False
        return new_state in (next_state(kind, state, move, service), prev_state(kind, state, move, service))
    if new_kind == kind and new_state == next_state(kind, state, move, service):
        return True
    if new_kind == kind and new_state == prev_state(kind, state, move, service):
        return True
    if new_kind == kind and new_state == 'reclaim' and can_reclaim(kind, state, move):
        return True
    if new_kind == 'business' and new_state == 'deliver' and can_convert(kind, state, move):
        return True
    if state == 'company' and new_state == 'company' and new_kind != kind:
        return True
    return False


def state_label(state):
    return dict(STATES).get(state, state)


def step_label(move, state, service=None):
    if (move or 'out') == 'out':
        track = track_for(service)
        if track and state in track['labels']:
            return track['labels'][state]
    return STEP_LABELS.get(move or 'out', STEP_LABELS['out']).get(state, state_label(state))


def track_tasks(service):
    track = track_for(service)
    return track['tasks'] if track else ()


def team_for(state):
    if state == 'company':
        return 'sales'
    if state in ('allocate', 'reclaim'):
        return 'allocator'
    if state == 'deliver':
        return 'delivery'
    if state in ('accept', 'decide', 'done'):
        return 'service'
    return None


def team_for_move(move, state, service=None):
    """Which group may approve the ticket out of this step."""
    move = move or 'out'
    if move == 'out':
        track = track_for(service)
        if track and state in track['teams']:
            return track['teams'][state]
        return team_for(state)
    if move == 'in':
        if state == 'company':
            return 'procurement'
        if state == 'allocate':
            return 'allocator'
        if state == 'deliver':
            return 'delivery'
        return None
    if move == 'back':
        if state == 'company':
            return 'sales'
        if state == 'reclaim':
            return 'allocator'
        return 'service' if state == 'done' else None
    if move == 'cutover':
        if state == 'company':
            return 'delivery'
        if state == 'allocate':
            return 'allocator'
        if state in ('deliver', 'accept', 'done'):
            return 'service'
    return None
