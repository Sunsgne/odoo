from odoo import models


class ResUsers(models.Model):
    _inherit = 'res.users'

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
