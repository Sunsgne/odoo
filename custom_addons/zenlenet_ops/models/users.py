from odoo import fields, models
from odoo.exceptions import UserError


class ResUsers(models.Model):
    _inherit = 'res.users'

    zenlenet_team = fields.Selection([
        ('sales', '销售'),
        ('delivery', '交付'),
        ('service', '售后'),
    ], string='分组')

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
    team = fields.Selection([
        ('sales', '销售'),
        ('delivery', '交付'),
        ('service', '售后'),
    ], string='分组')

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
            'zenlenet_team': self.team or False,
            'group_ids': [(4, self.env.ref('base.group_user').id)],
        })
        return {'type': 'ir.actions.act_window_close'}
