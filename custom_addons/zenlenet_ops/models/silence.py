from odoo import api, models


class PublisherWarrantyContract(models.AbstractModel):
    _inherit = 'publisher_warranty.contract'

    @api.model
    def update_notification(self, cron_mode=True):
        return True

    @api.model
    def _get_sys_logs(self):
        return {'messages': []}

    def _register_hook(self):
        cron = self.env.ref('mail.ir_cron_module_update_notification', raise_if_not_found=False)
        if cron and (cron.active or 'update_notification' in (cron.code or '')):
            cron.sudo().write({'active': False, 'code': 'pass'})
        provider = self.env.ref('auth_oauth.provider_openerp', raise_if_not_found=False)
        if provider and (provider.enabled or provider.client_id):
            provider.sudo().write({'enabled': False, 'client_id': False})
        vies = self.env.ref('base_vat.vies_iap_check_update', raise_if_not_found=False)
        if vies and (vies.active or 'vies' in (vies.code or '')):
            vies.sudo().write({'active': False, 'code': 'pass'})
        return super()._register_hook()
