"""Physical machines and virtual machines, hung the way NetBox hangs them.

A VM is not a free-floating row. It belongs to a site, runs on a device at that
site, and carries one primary IP plus the bandwidth being sold.
"""

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

DEVICE_STATUS = [
    ('active', '在用'),
    ('planned', '规划中'),
    ('offline', '离线'),
    ('decommissioning', '下线中'),
]
VM_STATUS = [
    ('active', '在用'),
    ('planned', '规划中'),
    ('offline', '离线'),
]


class ZenlenetDevice(models.Model):
    _name = 'zenlenet.device'
    _description = '物理机'
    _inherit = ['zenlenet.deletable']
    _order = 'name'

    name = fields.Char(string='名称', required=True, index=True)
    netbox_id = fields.Integer(string='NetBox ID', index=True, copy=False)
    netbox_synced = fields.Datetime(string='上次同步')
    datacenter_id = fields.Many2one('zenlenet.datacenter', string='机房', index=True, ondelete='restrict')
    role = fields.Char(string='角色')
    status = fields.Selection(DEVICE_STATUS, string='状态', default='active', required=True, index=True)
    serial = fields.Char(string='序列号')
    vm_ids = fields.One2many('zenlenet.vm', 'device_id', string='云主机')

    def _delete_snapshot(self):
        return {'status': self.status, 'vm_count': len(self.vm_ids)}

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get('netbox_skip_push'):
            for record in records:
                record._push()
        return records

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get('netbox_skip_push') and {'name', 'datacenter_id', 'status', 'serial', 'role'} & set(vals):
            for record in self:
                record._push()
        return result

    def _push(self):
        try:
            self.env['zenlenet.netbox'].push_device(self)
        except Exception as error:
            _logger.warning('NetBox device push skipped for %s: %s', self.id, type(error).__name__)

    def action_open_netbox(self):
        self.ensure_one()
        link = self.env['zenlenet.netbox'].public_link(f'/dcim/devices/{self.netbox_id}/')
        if not (self.netbox_id and link):
            return False
        return {'type': 'ir.actions.act_url', 'url': link, 'target': 'new'}


class ZenlenetVm(models.Model):
    _name = 'zenlenet.vm'
    _description = '云主机'
    _inherit = ['zenlenet.deletable']
    _order = 'name'

    name = fields.Char(string='名称', required=True, index=True)
    netbox_id = fields.Integer(string='NetBox ID', index=True, copy=False)
    netbox_synced = fields.Datetime(string='上次同步')
    iface_netbox_id = fields.Integer(copy=False)
    datacenter_id = fields.Many2one('zenlenet.datacenter', string='机房', required=True, index=True, ondelete='restrict')
    device_id = fields.Many2one(
        'zenlenet.device', string='物理机', index=True, ondelete='restrict',
        domain="[('datacenter_id', '=', datacenter_id)]",
    )
    address_id = fields.Many2one('zenlenet.address', string='IP', index=True, ondelete='set null')
    ip_text = fields.Char(string='IP（NetBox）')
    bandwidth_mbps = fields.Integer(string='带宽 (Mbps)')
    partner_id = fields.Many2one('res.partner', string='客户', domain=[('is_company', '=', True)], index=True)
    status = fields.Selection(VM_STATUS, string='状态', default='active', required=True, index=True)
    vcpus = fields.Float(string='vCPU')
    memory = fields.Integer(string='内存 (MB)')

    def _delete_snapshot(self):
        return {'status': self.status, 'partner': bool(self.partner_id)}

    @api.onchange('address_id')
    def _onchange_address(self):
        for record in self:
            if record.address_id:
                record.ip_text = record.address_id.address

    @api.onchange('device_id')
    def _onchange_device(self):
        for record in self:
            if record.device_id and record.device_id.datacenter_id:
                record.datacenter_id = record.device_id.datacenter_id

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get('netbox_skip_push'):
            for record in records:
                record._push()
        return records

    def write(self, vals):
        result = super().write(vals)
        watched = {'name', 'datacenter_id', 'device_id', 'address_id', 'bandwidth_mbps', 'status', 'vcpus', 'memory'}
        if not self.env.context.get('netbox_skip_push') and watched & set(vals):
            for record in self:
                record._push()
        return result

    def _push(self):
        try:
            self.env['zenlenet.netbox'].push_vm(self)
        except Exception as error:
            _logger.warning('NetBox VM push skipped for %s: %s', self.id, type(error).__name__)

    def action_open_netbox(self):
        self.ensure_one()
        link = self.env['zenlenet.netbox'].public_link(f'/virtualization/virtual-machines/{self.netbox_id}/')
        if not (self.netbox_id and link):
            return False
        return {'type': 'ir.actions.act_url', 'url': link, 'target': 'new'}
