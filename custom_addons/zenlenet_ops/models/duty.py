from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.zenlenet_ops.duty import (
    apply_swap,
    coverage,
    month_days,
    next_state,
    offset_label,
    overnight,
    parse_hhmm,
    person_counts,
    week_days,
    weekday_label,
)

TIMEZONES = [
    ('Asia/Singapore', 'Asia/Singapore'),
    ('Asia/Shanghai', 'Asia/Shanghai'),
    ('Asia/Hong_Kong', 'Asia/Hong_Kong'),
    ('Asia/Tokyo', 'Asia/Tokyo'),
    ('America/New_York', 'America/New_York'),
    ('America/Los_Angeles', 'America/Los_Angeles'),
    ('Europe/London', 'Europe/London'),
    ('UTC', 'UTC'),
]
KINDS = [('day', '白班'), ('night', '夜班'), ('onsite', '现场')]
ENABLED = [('enabled', '启用'), ('disabled', '停用')]
SHEET_STATES = [('draft', '草稿'), ('published', '已发布')]
SWAP_STATES = [
    ('draft', '草稿'),
    ('peer', '待对方同意'),
    ('lead', '待组长审批'),
    ('approved', '已审批'),
    ('refused', '已拒绝'),
    ('withdrawn', '已撤回'),
]


def _clock(value):
    if parse_hhmm(value or '') is None:
        raise UserError('时间写成 09:00 这样。')
    return value


class ZenlenetDutyRegion(models.Model):
    _name = 'zenlenet.duty.region'
    _description = '排班区域'
    _inherit = ['zenlenet.deletable']
    _order = 'name, id'

    name = fields.Char(string='区域名称', required=True)
    code = fields.Char(string='区域编码', required=True, index=True)
    country = fields.Char(string='国家代码')
    tz = fields.Selection(TIMEZONES, string='时区', required=True, default='Asia/Singapore')
    week_start = fields.Selection([('sun', '星期日'), ('mon', '星期一')], string='周起始日', default='sun', required=True)
    state = fields.Selection(ENABLED, string='状态', default='enabled', required=True, index=True)
    note = fields.Char(string='备注')
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)

    _region_code = models.Constraint('unique(code, company_id)', '这个区域编码已经有了。')


class ZenlenetDutyGroup(models.Model):
    _name = 'zenlenet.duty.group'
    _description = '排班分组'
    _inherit = ['zenlenet.deletable']
    _order = 'name, id'

    name = fields.Char(string='分组名称', required=True)
    code = fields.Char(string='分组编码', required=True, index=True)
    member_ids = fields.Many2many('res.users', string='成员')
    state = fields.Selection(ENABLED, string='状态', default='enabled', required=True, index=True)
    note = fields.Char(string='备注')
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)

    _group_code = models.Constraint('unique(code, company_id)', '这个分组编码已经有了。')


class ZenlenetDutyShift(models.Model):
    _name = 'zenlenet.duty.shift'
    _description = '班次'
    _inherit = ['zenlenet.deletable']
    _order = 'region_id, start, id'

    name = fields.Char(string='班次名称', required=True)
    code = fields.Char(string='班次编码', required=True, index=True)
    region_id = fields.Many2one('zenlenet.duty.region', string='区域', required=True, index=True)
    group_id = fields.Many2one('zenlenet.duty.group', string='班次组')
    start = fields.Char(string='开始时间', required=True, default='09:00')
    end = fields.Char(string='结束时间', required=True, default='21:00')
    kind = fields.Selection(KINDS, string='类型', required=True, default='day')
    remote = fields.Boolean(string='远程')
    need = fields.Integer(string='人数', default=1, required=True)
    state = fields.Selection(ENABLED, string='状态', default='enabled', required=True, index=True)
    note = fields.Char(string='备注')
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)

    _shift_code = models.Constraint('unique(code, company_id)', '这个班次编码已经有了。')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'start' in vals:
                vals['start'] = _clock(vals['start'])
            if 'end' in vals:
                vals['end'] = _clock(vals['end'])
            if vals.get('need', 1) < 0:
                raise UserError('人数不能是负数。')
        return super().create(vals_list)

    def write(self, vals):
        if 'start' in vals:
            vals['start'] = _clock(vals['start'])
        if 'end' in vals:
            vals['end'] = _clock(vals['end'])
        if 'need' in vals and vals['need'] < 0:
            raise UserError('人数不能是负数。')
        return super().write(vals)


class ZenlenetDutySheet(models.Model):
    _name = 'zenlenet.duty.sheet'
    _description = '排班表'
    _inherit = ['zenlenet.deletable']
    _order = 'name, id'

    name = fields.Char(string='排班表名称', required=True)
    code = fields.Char(string='排班表编码', required=True, index=True)
    region_ids = fields.Many2many('zenlenet.duty.region', string='区域')
    state = fields.Selection(SHEET_STATES, string='状态', default='draft', required=True, index=True)
    note = fields.Char(string='备注')
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    cell_ids = fields.One2many('zenlenet.duty.cell', 'sheet_id', string='班次格')

    _sheet_code = models.Constraint('unique(code, company_id)', '这个排班表编码已经有了。')

    def action_publish(self):
        self.write({'state': 'published'})
        return True

    def _shifts(self):
        self.ensure_one()
        return self.env['zenlenet.duty.shift'].search([
            ('company_id', '=', self.company_id.id),
            ('state', '=', 'enabled'),
            ('region_id', 'in', self.region_ids.ids),
            ('region_id.state', '=', 'enabled'),
        ])

    def _ensure(self, days):
        self.ensure_one()
        Cell = self.env['zenlenet.duty.cell'].sudo()
        existing = {
            (cell.shift_id.id, cell.date)
            for cell in Cell.search([('sheet_id', '=', self.id), ('date', 'in', days)])
        }
        rows = []
        for shift in self._shifts():
            for day in days:
                if (shift.id, day) in existing:
                    continue
                rows.append({
                    'sheet_id': self.id,
                    'shift_id': shift.id,
                    'date': day,
                    'need': shift.need,
                })
        if rows:
            Cell.create(rows)
        return True

    @api.model
    def calendar(self, sheet_id=False, anchor=False, mode='week', region_id=False, user_id=False, shift_id=False, kind=False):
        company = self.env.company
        sheets = self.search([('company_id', '=', company.id)], order='state desc, name, id')
        published = sheets.filtered(lambda sheet: sheet.state == 'published')
        tabs = sheets if self._can_edit() else (published or sheets)
        sheet = self.browse(sheet_id).exists() if sheet_id else self.browse()
        if not sheet or sheet.company_id != company:
            sheet = tabs[:1]
        preference = self.env['zenlenet.duty.preference'].mine()
        day = fields.Date.to_date(anchor) if anchor else fields.Date.context_today(self)
        starts = preference['week_start'] or 'sun'
        if not kind and preference.get('prefer') in ('day', 'night'):
            kind = preference['prefer']
        days = week_days(day, starts) if mode != 'month' else month_days(day, starts)
        if sheet and (sheet.state == 'published' or self._can_edit()):
            sheet._ensure(days)
        payload = self._board(sheet, days, day, region_id, user_id, shift_id, kind) if sheet else {'days': [], 'stats': coverage([])}
        payload.update({
            'sheets': [{'id': item.id, 'name': item.name, 'state': item.state} for item in tabs],
            'sheet_id': sheet.id if sheet else False,
            'anchor': fields.Date.to_string(day),
            'mode': 'month' if mode == 'month' else 'week',
            'week_start': starts,
            'preference': preference,
            'can_edit': self._can_edit(),
            'regions': [{'id': region.id, 'name': region.name} for region in sheet.region_ids] if sheet else [],
            'shifts': [{'id': shift.id, 'name': shift.name} for shift in sheet._shifts()] if sheet else [],
            'users': [{'id': user.id, 'name': user.name} for user in sheet._shifts().group_id.member_ids] if sheet else [],
        })
        return payload

    def _can_edit(self):
        user = self.env.user
        return bool(
            user.has_group('zenlenet_ops.group_manager')
            or user.has_group('zenlenet_ops.group_delivery')
            or user.has_group('zenlenet_ops.group_service')
        )

    def _board(self, sheet, days, focus, region_id, user_id, shift_id, kind):
        cells = self.env['zenlenet.duty.cell'].search([
            ('sheet_id', '=', sheet.id),
            ('date', 'in', days),
        ])
        by_key = {(cell.shift_id.id, cell.date): cell for cell in cells}
        regions = sheet.region_ids.filtered(lambda region: region.state == 'enabled')
        if region_id:
            regions = regions.filtered(lambda region: region.id == region_id)
        shifts = sheet._shifts().filtered(lambda shift: shift.region_id in regions)
        if shift_id:
            shifts = shifts.filtered(lambda shift: shift.id == shift_id)
        if kind in ('day', 'night', 'onsite'):
            shifts = shifts.filtered(lambda shift: shift.kind == kind)
        flat = []
        columns = []
        today = fields.Date.context_today(self)
        for day in days:
            region_rows = []
            for region in regions:
                shift_rows = []
                for shift in shifts.filtered(lambda item: item.region_id == region):
                    cell = by_key.get((shift.id, day))
                    people = []
                    if cell:
                        for assignment in cell.assignment_ids:
                            people.append({'id': assignment.user_id.id, 'name': assignment.user_id.name})
                    if user_id and not any(person['id'] == user_id for person in people):
                        continue
                    row = {
                        'cell_id': cell.id if cell else False,
                        'shift_id': shift.id,
                        'name': shift.name,
                        'kind': shift.kind,
                        'start': shift.start,
                        'end': shift.end,
                        'overnight': overnight(shift.start, shift.end),
                        'remote': shift.remote,
                        'filled': len(people),
                        'need': cell.need if cell else shift.need,
                        'people': people,
                    }
                    row['short'] = row['filled'] < row['need']
                    shift_rows.append(row)
                    flat.append(row)
                if shift_rows:
                    region_rows.append({
                        'id': region.id,
                        'name': region.name,
                        'tz': region.tz,
                        'offset': offset_label(region.tz, day),
                        'shifts': shift_rows,
                    })
            columns.append({
                'date': fields.Date.to_string(day),
                'weekday': weekday_label(day),
                'today': day == today,
                'in_month': day.month == focus.month,
                'regions': region_rows,
            })
        counts = {}
        names = {}
        for person_id, count in person_counts(flat):
            counts[person_id] = count
        users = self.env['res.users'].browse([key for key in counts if key])
        for user in users:
            names[user.id] = user.name
        stats = coverage(flat)
        stats['swaps'] = self.env['zenlenet.duty.swap'].search_count([
            ('sheet_id', '=', sheet.id),
            ('date', '>=', days[0]),
            ('date', '<=', days[-1]),
        ]) if days else 0
        stats['approved'] = self.env['zenlenet.duty.swap'].search_count([
            ('sheet_id', '=', sheet.id),
            ('state', '=', 'approved'),
            ('date', '>=', days[0]),
            ('date', '<=', days[-1]),
        ]) if days else 0
        stats['people'] = [{'id': key, 'name': names.get(key, ''), 'count': counts[key]} for key in counts]
        kinds = {}
        for row in flat:
            kinds[row['kind']] = kinds.get(row['kind'], 0) + 1
        stats['kinds'] = [{'key': key, 'label': dict(KINDS).get(key, key), 'count': kinds[key]} for key in kinds]
        return {'days': columns, 'stats': stats}


class ZenlenetDutyCell(models.Model):
    _name = 'zenlenet.duty.cell'
    _description = '班次格'
    _order = 'date, shift_id'
    _rec_name = 'date'

    sheet_id = fields.Many2one('zenlenet.duty.sheet', required=True, ondelete='cascade', index=True)
    shift_id = fields.Many2one('zenlenet.duty.shift', required=True, ondelete='cascade', index=True)
    date = fields.Date(string='日期', required=True, index=True)
    need = fields.Integer(string='人数', default=1, required=True)
    assignment_ids = fields.One2many('zenlenet.duty.assignment', 'cell_id', string='人员')

    _cell_key = models.Constraint('unique(sheet_id, shift_id, date)', '这一天的这个班次已经有了。')

    def detail(self):
        self.ensure_one()
        group = self.shift_id.group_id
        users = group.member_ids if group and group.member_ids else self.env['res.users'].search([
            ('share', '=', False),
            ('active', '=', True),
        ], limit=80)
        assigned = set(self.assignment_ids.mapped('user_id').ids)
        extra = self.assignment_ids.mapped('user_id') - users
        people = []
        for user in users | extra:
            people.append({'id': user.id, 'name': user.name, 'on': user.id in assigned})
        return {
            'cell_id': self.id,
            'shift_id': self.shift_id.id,
            'name': self.shift_id.name,
            'date': fields.Date.to_string(self.date),
            'need': self.need,
            'people': people,
        }

    def set_need(self, need):
        self.check_access('write')
        if int(need) < 0:
            raise UserError('人数不能是负数。')
        self.write({'need': int(need)})
        return True

    def set_member(self, user_id, present):
        self.check_access('write')
        self.ensure_one()
        user = self.env['res.users'].browse(int(user_id)).exists()
        if not user or user.share:
            raise UserError('这个人员不存在。')
        group = self.shift_id.group_id
        if group and group.member_ids and user not in group.member_ids:
            raise UserError('这个人员不在该班次组里。')
        found = self.assignment_ids.filtered(lambda row: row.user_id == user)
        if present and not found:
            self.env['zenlenet.duty.assignment'].create({'cell_id': self.id, 'user_id': user.id})
        if not present and found:
            found.unlink()
        return True


class ZenlenetDutyAssignment(models.Model):
    _name = 'zenlenet.duty.assignment'
    _description = '排班人员'
    _order = 'id'

    cell_id = fields.Many2one('zenlenet.duty.cell', required=True, ondelete='cascade', index=True)
    user_id = fields.Many2one('res.users', string='人员', required=True, index=True)

    _assignment_key = models.Constraint('unique(cell_id, user_id)', '这个人已经在这个班次里。')


class ZenlenetDutySwap(models.Model):
    _name = 'zenlenet.duty.swap'
    _description = '换班'
    _inherit = ['zenlenet.deletable']
    _order = 'id desc'
    _rec_name = 'date'

    sheet_id = fields.Many2one('zenlenet.duty.sheet', string='排班表', required=True, index=True)
    date = fields.Date(string='日期', required=True, index=True)
    applicant_id = fields.Many2one('res.users', string='申请人', required=True, default=lambda self: self.env.user)
    from_shift_id = fields.Many2one('zenlenet.duty.shift', string='原班次', required=True)
    target_id = fields.Many2one('res.users', string='目标人员', required=True)
    to_shift_id = fields.Many2one('zenlenet.duty.shift', string='目标班次', required=True)
    from_cell_id = fields.Many2one('zenlenet.duty.cell', string='原格子', readonly=True)
    to_cell_id = fields.Many2one('zenlenet.duty.cell', string='目标格子', readonly=True)
    reason = fields.Char(string='申请原因')
    state = fields.Selection(SWAP_STATES, string='状态', default='draft', required=True, index=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)

    def _step(self, event):
        for record in self:
            state = next_state(record.state, event)
            if not state:
                raise UserError('当前状态不能做这一步。')
            record.state = state
        return True

    def _cells(self):
        self.ensure_one()
        Cell = self.env['zenlenet.duty.cell']
        source = Cell.search([
            ('sheet_id', '=', self.sheet_id.id),
            ('shift_id', '=', self.from_shift_id.id),
            ('date', '=', self.date),
        ], limit=1)
        dest = Cell.search([
            ('sheet_id', '=', self.sheet_id.id),
            ('shift_id', '=', self.to_shift_id.id),
            ('date', '=', self.date),
        ], limit=1)
        if not source or not dest or source == dest:
            raise UserError('这一天没有可对换的两个班次。')
        return source, dest

    def action_submit(self):
        for record in self:
            if record.applicant_id != self.env.user and not self.env.user.has_group('zenlenet_ops.group_manager'):
                raise UserError('只能提交自己的换班。')
            source, dest = record._cells()
            if record.applicant_id not in source.assignment_ids.user_id:
                raise UserError('申请人不在原班次里。')
            if record.target_id not in dest.assignment_ids.user_id:
                raise UserError('目标人员不在目标班次里。')
            record.write({'from_cell_id': source.id, 'to_cell_id': dest.id})
        return self._step('submit')

    def action_peer(self):
        for record in self:
            if record.target_id != self.env.user and not self.env.user.has_group('zenlenet_ops.group_manager'):
                raise UserError('要目标人员同意。')
        return self._step('peer')

    def action_approve(self):
        if not self.env.user.has_group('zenlenet_ops.group_manager'):
            raise UserError('要组长审批。')
        for record in self:
            state = next_state(record.state, 'approve')
            if not state:
                raise UserError('当前状态不能做这一步。')
            source = record.from_cell_id
            dest = record.to_cell_id
            moved = apply_swap(
                set(source.assignment_ids.mapped('user_id').ids),
                set(dest.assignment_ids.mapped('user_id').ids),
                record.applicant_id.id,
                record.target_id.id,
            )
            if not moved:
                raise UserError('两边的人员已经变了，不能按原申请对换。')
            source_ids, dest_ids = moved
            record._rewrite(source, source_ids)
            record._rewrite(dest, dest_ids)
            record.state = state
        return True

    def _rewrite(self, cell, user_ids):
        current = {row.user_id.id: row for row in cell.assignment_ids}
        for user_id, row in current.items():
            if user_id not in user_ids:
                row.unlink()
        Assignment = self.env['zenlenet.duty.assignment']
        for user_id in user_ids:
            if user_id not in current:
                Assignment.create({'cell_id': cell.id, 'user_id': user_id})

    def action_refuse(self):
        manager = self.env.user.has_group('zenlenet_ops.group_manager')
        for record in self:
            if record.state == 'peer' and record.target_id != self.env.user and not manager:
                raise UserError('要目标人员拒绝。')
            if record.state == 'lead' and not manager:
                raise UserError('要组长拒绝。')
        return self._step('refuse')

    def action_withdraw(self):
        manager = self.env.user.has_group('zenlenet_ops.group_manager')
        for record in self:
            if record.applicant_id != self.env.user and not manager:
                raise UserError('只能撤回自己的换班。')
        return self._step('withdraw')


class ZenlenetDutyPreference(models.Model):
    _name = 'zenlenet.duty.preference'
    _description = '排班个人设置'
    _order = 'id'

    user_id = fields.Many2one('res.users', required=True, index=True)
    week_start = fields.Selection([('sun', '星期日'), ('mon', '星期一')], string='周历显示', default='sun', required=True)
    prefer = fields.Selection([('any', '不限'), ('day', '白班'), ('night', '夜班')], string='排班偏好', default='any', required=True)

    _preference_user = models.Constraint('unique(user_id)', '这个人的排班设置已经有了。')

    @api.model
    def mine(self):
        found = self.sudo().search([('user_id', '=', self.env.uid)], limit=1)
        if not found:
            return {'week_start': 'sun', 'prefer': 'any'}
        return {'week_start': found.week_start, 'prefer': found.prefer}

    @api.model
    def save_mine(self, week_start='sun', prefer='any'):
        if week_start not in ('sun', 'mon'):
            week_start = 'sun'
        if prefer not in ('any', 'day', 'night'):
            prefer = 'any'
        found = self.sudo().search([('user_id', '=', self.env.uid)], limit=1)
        values = {'week_start': week_start, 'prefer': prefer}
        if found:
            found.write(values)
        else:
            self.sudo().create({'user_id': self.env.uid, **values})
        return self.mine()
