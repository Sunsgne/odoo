from odoo import api, fields, models
from odoo.exceptions import UserError


class ResUsers(models.Model):
    _inherit = 'res.users'

    zenlenet_team = fields.Selection([
        ('sales', '销售'),
        ('delivery', '交付'),
        ('service', '售后'),
    ], string='分组')
    zenlenet_in_sales = fields.Boolean(compute='_compute_zenlenet_in_groups', search='_search_zenlenet_in_sales')
    zenlenet_in_allocator = fields.Boolean(compute='_compute_zenlenet_in_groups', search='_search_zenlenet_in_allocator')
    zenlenet_in_delivery = fields.Boolean(compute='_compute_zenlenet_in_groups', search='_search_zenlenet_in_delivery')
    zenlenet_in_service = fields.Boolean(compute='_compute_zenlenet_in_groups', search='_search_zenlenet_in_service')
    zenlenet_in_procurement = fields.Boolean(compute='_compute_zenlenet_in_groups', search='_search_zenlenet_in_procurement')
    zenlenet_role_ids = fields.Many2many(
        'res.groups', string='岗位', compute='_compute_roles', inverse='_inverse_roles',
        domain=lambda self: [('privilege_id', '=', self.env.ref('zenlenet_ops.privilege_zenlenet').id)],
    )
    zenlenet_role_names = fields.Char(string='岗位名称', compute='_compute_roles')

    @api.depends('all_group_ids')
    def _compute_zenlenet_in_groups(self):
        flags = {
            'zenlenet_in_sales': self.env.ref('zenlenet_ops.group_sales', raise_if_not_found=False),
            'zenlenet_in_allocator': self.env.ref('zenlenet_ops.group_allocator', raise_if_not_found=False),
            'zenlenet_in_delivery': self.env.ref('zenlenet_ops.group_delivery', raise_if_not_found=False),
            'zenlenet_in_service': self.env.ref('zenlenet_ops.group_service', raise_if_not_found=False),
            'zenlenet_in_procurement': self.env.ref('zenlenet_ops.group_procurement', raise_if_not_found=False),
        }
        for user in self:
            ids = set(user.all_group_ids.ids)
            for name, group in flags.items():
                user[name] = bool(group and group.id in ids)

    def _search_zenlenet_group(self, xmlid, operator, value):
        group = self.env.ref(xmlid, raise_if_not_found=False)
        if not group:
            return [('id', '=', 0)]
        member = (operator == '=' and value) or (operator == '!=' and not value)
        return [('all_group_ids', 'in' if member else 'not in', group.ids)]

    def _search_zenlenet_in_sales(self, operator, value):
        return self._search_zenlenet_group('zenlenet_ops.group_sales', operator, value)

    def _search_zenlenet_in_allocator(self, operator, value):
        return self._search_zenlenet_group('zenlenet_ops.group_allocator', operator, value)

    def _search_zenlenet_in_delivery(self, operator, value):
        return self._search_zenlenet_group('zenlenet_ops.group_delivery', operator, value)

    def _search_zenlenet_in_service(self, operator, value):
        return self._search_zenlenet_group('zenlenet_ops.group_service', operator, value)

    def _search_zenlenet_in_procurement(self, operator, value):
        return self._search_zenlenet_group('zenlenet_ops.group_procurement', operator, value)

    def _zenlenet_role_groups(self):
        privilege = self.env.ref('zenlenet_ops.privilege_zenlenet', raise_if_not_found=False)
        return self.env['res.groups'].sudo().search([('privilege_id', '=', privilege.id)]) if privilege else self.env['res.groups']

    @api.depends('group_ids', 'all_group_ids')
    def _compute_roles(self):
        roles = self._zenlenet_role_groups()
        for user in self:
            mine = user.all_group_ids & roles
            user.zenlenet_role_ids = mine
            user.zenlenet_role_names = '、'.join(mine.sorted('sequence').mapped('name'))

    def _inverse_roles(self):
        roles = self._zenlenet_role_groups()
        for user in self:
            keep = user.group_ids - roles
            user.sudo().write({'group_ids': [(6, 0, (keep | user.zenlenet_role_ids).ids)]})

    def _generate_signup_values(self, provider, validation, params):
        values = super()._generate_signup_values(provider, validation, params)
        email = validation.get('email') or validation.get('preferred_username') or validation.get('upn')
        if email and '@' in str(email):
            values.update({
                'login': email,
                'email': email,
                'name': validation.get('name') or email,
            })
        return values

    def _auth_oauth_signin(self, provider, validation, params):
        login = super()._auth_oauth_signin(provider, validation, params)
        user = self.sudo().search([('login', '=', login)], limit=1)
        internal = self.env.ref('base.group_user')
        if user and internal not in user.group_ids:
            user.sudo().write({'group_ids': [(4, internal.id)]})
        return login

    def action_zenlenet_add_user(self):
        return {
            'type': 'ir.actions.act_window',
            'name': '添加账号',
            'res_model': 'zenlenet.user.add',
            'view_mode': 'form',
            'target': 'new',
        }


class ZenlenetUserAdd(models.TransientModel):
    _name = 'zenlenet.user.add'
    _description = '添加账号'

    name = fields.Char(string='姓名', required=True)
    login = fields.Char(string='登录名', required=True)
    password = fields.Char(string='密码', required=True)
    role_ids = fields.Many2many(
        'res.groups', string='岗位',
        domain=lambda self: [('privilege_id', '=', self.env.ref('zenlenet_ops.privilege_zenlenet').id)],
    )

    def action_create(self):
        self.ensure_one()
        login = (self.login or '').strip()
        if not login or not (self.password or '').strip():
            raise UserError('请填写登录名和密码。')
        users = self.env['res.users'].sudo()
        if users.search_count([('login', '=', login)]):
            raise UserError('这个登录名已经有了。')
        users.with_context(no_reset_password=True).create({
            'name': self.name.strip(),
            'login': login,
            'email': login if '@' in login else False,
            'password': self.password,
            'share': False,
            'group_ids': [(6, 0, (self.env.ref('base.group_user') | self.role_ids).ids)],
        })
        return {'type': 'ir.actions.act_window_close'}
