# models/user_group_config.py
from odoo import models, fields, api

class AutoEmailGroupConfig(models.Model):
    _name = 'auto.email.group.config'
    _description = 'Auto Email Activity Group Configuration'
    _rec_name = 'group_id'
    
    group_id = fields.Many2one(
        'res.groups',
        string='User Group',
        required=True,
        help='User group that will have automatic email activities created'
    )
    
    active = fields.Boolean(
        string='Active',
        default=True,
        help='If unchecked, this group will not trigger activity creation'
    )
    
    user_count = fields.Integer(
        string='Active Users',
        compute='_compute_user_count',
        help='Number of active users in this group'
    )
    
    @api.depends('group_id')
    def _compute_user_count(self):
        for record in self:
            if record.group_id:
                record.user_count = len(record.group_id.users.filtered('active'))
            else:
                record.user_count = 0
    
    _sql_constraints = [
        ('unique_group', 'UNIQUE(group_id)', 'Each user group can only be selected once.')
    ]