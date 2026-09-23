from odoo import models
from odoo.exceptions import UserError

from odoo.addons.zenlenet_ops import deletion


class ZenlenetDeletable(models.AbstractModel):
    """Delete guard shared by every business record of the console.

    Access rights decide *who* may call unlink; this mixin decides *when* a record is still safe to
    remove. Cron jobs and the loader run as superuser and are not affected.
    """

    _name = 'zenlenet.deletable'
    _description = '删除保护'

    def _delete_snapshot(self):
        snap = {}
        if 'state' in self._fields:
            snap['state'] = self.state
        if 'status' in self._fields:
            snap['status'] = self.status
        return snap

    def unlink(self):
        if not self.env.su:
            is_manager = self.env.user.has_group('zenlenet_ops.group_manager')
            for record in self:
                reason = deletion.can_delete(self._name, record._delete_snapshot(), is_manager, in_role=True)
                if reason:
                    raise UserError(f'{record.display_name}：{reason}')
        return super().unlink()
