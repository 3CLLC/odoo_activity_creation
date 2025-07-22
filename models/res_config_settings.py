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
    
    auto_email_user_groups = fields.Many2many(
        'res.groups',
        string='User Groups',
        help='Select which user groups will have automatic email activities created'
    )
    
    total_affected_users = fields.Integer(
        string="Total Affected Users",
        compute='_compute_total_affected_users',
        help="Total number of active users across all selected groups"
    )
    
    @api.depends('auto_email_user_groups', 'auto_email_user_groups.users')
    def _compute_total_affected_users(self):
        """Compute total number of users that will be affected by this configuration."""
        for record in self:
            # Get unique users across all selected groups
            all_users = record.auto_email_user_groups.mapped('users').filtered('active')
            # Remove duplicates by converting to set and back
            unique_users = self.env['res.users'].browse(list(set(all_users.ids)))
            record.total_affected_users = len(unique_users)
    
    @api.constrains('auto_email_activity_enabled', 'auto_email_user_groups')
    def _check_configuration_validity(self):
        """Validate configuration makes sense."""
        for record in self:
            if record.auto_email_activity_enabled and not record.auto_email_user_groups:
                raise ValidationError(_(
                    "Auto Email Activity Creation is enabled but no user groups are selected. "
                    "Please select at least one user group."
                ))
    
    @api.model
    def get_values(self):
        """Override to load current group configuration."""
        res = super(ResConfigSettings, self).get_values()
        
        # Load groups from active configurations
        active_configs = self.env['auto.email.group.config'].search([('active', '=', True)])
        selected_group_ids = active_configs.mapped('group_id.id')
        res['auto_email_user_groups'] = [(6, 0, selected_group_ids)]
        
        return res
    
    def set_values(self):
        """Override to save group configuration."""
        super(ResConfigSettings, self).set_values()
        
        # Sync the selected groups with auto.email.group.config records
        self._sync_group_configurations()
        
        # Log configuration changes for audit purposes
        if self.auto_email_activity_enabled:
            group_names = self.auto_email_user_groups.mapped('name')
            self.env['ir.logging'].sudo().create({
                'name': 'auto_email_activity_creation',
                'type': 'server',
                'level': 'INFO',
                'dbname': self.env.cr.dbname,
                'message': f"Auto Email Activity Configuration updated. Active groups: {', '.join(group_names)}",
                'func': 'set_values',
                'line': '1'
            })
    
    def _sync_group_configurations(self):
        """Sync selected groups with auto.email.group.config records."""
        # Get currently selected group IDs
        selected_group_ids = set(self.auto_email_user_groups.ids)
        
        # Get existing config records
        existing_configs = self.env['auto.email.group.config'].search([])
        existing_group_ids = set(existing_configs.mapped('group_id.id'))
        
        # Groups to add (selected but not in config)
        groups_to_add = selected_group_ids - existing_group_ids
        
        # Groups to activate (selected and in config but inactive)
        groups_to_activate = selected_group_ids & existing_group_ids
        
        # Groups to deactivate (in config but not selected)
        groups_to_deactivate = existing_group_ids - selected_group_ids
        
        # Create new config records for new groups
        for group_id in groups_to_add:
            self.env['auto.email.group.config'].create({
                'group_id': group_id,
                'active': True
            })
        
        # Activate selected existing configs
        configs_to_activate = existing_configs.filtered(
            lambda c: c.group_id.id in groups_to_activate
        )
        configs_to_activate.write({'active': True})
        
        # Deactivate unselected configs
        configs_to_deactivate = existing_configs.filtered(
            lambda c: c.group_id.id in groups_to_deactivate
        )
        configs_to_deactivate.write({'active': False})
    
    def action_view_group_configs(self):
        """Action to view and manage group configurations."""
        return {
            'name': _('Auto Email Activity Group Configuration'),
            'type': 'ir.actions.act_window',
            'res_model': 'auto.email.group.config',
            'view_mode': 'list,form',
            'domain': [('active', '=', True)],
            'context': {
                'create': True,
                'edit': True,
                'delete': False,  # Don't allow deletion, only deactivation
            }
        }