from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'
    
    auto_email_activity_enabled = fields.Boolean(
        string="Enable Auto Email Activity Creation",
        config_parameter='auto_email_activity_creation.enabled',
        default=True,
        help="When enabled, a completed activity will be automatically created when users from "
             "selected groups send external emails through chatter in Helpdesk and Sales apps. "
             "This provides automatic tracking of all external communications."
    )
    
    selected_groups_ids = fields.Many2many(
        'auto.email.group.config',
        string='User Groups',
        help='Select which user groups will have automatic email activities created'
    )
    
    total_affected_users = fields.Integer(
        string="Total Affected Users",
        compute='_compute_total_affected_users',
        help="Total number of active users across all selected groups"
    )
    
    @api.depends('selected_groups_ids', 'selected_groups_ids.active', 'selected_groups_ids.user_count')
    def _compute_total_affected_users(self):
        """Compute total number of users that will be affected by this configuration."""
        for record in self:
            active_groups = record.selected_groups_ids.filtered('active')
            record.total_affected_users = sum(group.user_count for group in active_groups)
    
    @api.constrains('auto_email_activity_enabled', 'selected_groups_ids')
    def _check_configuration_validity(self):
        """Validate configuration makes sense."""
        for record in self:
            if record.auto_email_activity_enabled:
                active_groups = record.selected_groups_ids.filtered('active')
                if not active_groups:
                    raise ValidationError(_(
                        "Auto Email Activity Creation is enabled but no active user groups are selected. "
                        "Please select at least one active user group."
                    ))
    
    @api.model
    def get_values(self):
        """Override to load current group configuration."""
        res = super(ResConfigSettings, self).get_values()
        
        # Load all active group configurations
        active_groups = self.env['auto.email.group.config'].search([('active', '=', True)])
        res['selected_groups_ids'] = [(6, 0, active_groups.ids)]
        
        return res
    
    def set_values(self):
        """Override to save group configuration."""
        super(ResConfigSettings, self).set_values()
        # The Many2many field handles the configuration updates automatically
        
        # Log configuration changes for audit purposes
        if self.auto_email_activity_enabled:
            active_groups = self.selected_groups_ids.filtered('active')
            group_names = [group.group_id.name for group in active_groups]
            self.env['ir.logging'].sudo().create({
                'name': 'auto_email_activity_creation',
                'type': 'server',
                'level': 'INFO',
                'dbname': self.env.cr.dbname,
                'message': f"Auto Email Activity Configuration updated. Active groups: {', '.join(group_names)}",
                'func': 'set_values',
                'line': '1'
            })
    
    def action_add_user_group(self):
        """Action to open wizard for adding new user groups."""
        return {
            'name': _('Add User Groups'),
            'type': 'ir.actions.act_window',
            'res_model': 'auto.email.group.config',
            'view_mode': 'tree,form',
            'target': 'new',
            'context': {
                'default_active': True,
            }
        }
    
    def action_view_selected_groups(self):
        """Action to view and manage selected user groups."""
        return {
            'name': _('Manage User Groups for Auto Email Activities'),
            'type': 'ir.actions.act_window',
            'res_model': 'auto.email.group.config',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', self.selected_groups_ids.ids)],
            'context': {
                'create': True,
                'edit': True,
                'delete': True,
            }
        }