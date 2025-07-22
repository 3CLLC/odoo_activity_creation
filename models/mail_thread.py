from odoo import models, api, fields, _
from odoo.exceptions import UserError, AccessError
import logging

_logger = logging.getLogger(__name__)

class MailThread(models.AbstractModel):
    _inherit = 'mail.thread'
    
    @api.returns('mail.message', lambda value: value.id)
    def message_post(self, **kwargs):
        """Override message_post to create an activity when sending an external email via chatter."""
        
        # Debug logging - let's see what's happening
        _logger.info(f"=== DEBUG: message_post called on {self._name} ===")
        _logger.info(f"DEBUG: kwargs = {kwargs}")
        _logger.info(f"DEBUG: context = {self.env.context}")
        
        # Call original method to create the message first
        message = super(MailThread, self).message_post(**kwargs)
        
        _logger.info(f"DEBUG: Created message ID {message.id if message else 'None'}")
        if message:
            _logger.info(f"DEBUG: Message type = {message.message_type}")
            _logger.info(f"DEBUG: Message email_from = {message.email_from}")
            _logger.info(f"DEBUG: Message partner_ids = {message.partner_ids}")
            _logger.info(f"DEBUG: Message author_id = {message.author_id}")
        
        # Skip processing if this is a recursive call or system-generated message
        if self.env.context.get('auto_email_activity_skip'):
            _logger.info("DEBUG: Skipping due to context flag")
            return message
            
        # Only process email messages
        if not message or message.message_type != 'email':
            _logger.info(f"DEBUG: Skipping - not email message (type: {message.message_type if message else 'None'})")
            return message
            
        # Check if feature is enabled
        try:
            enabled = self.env['ir.config_parameter'].get_param('auto_email_activity_creation.enabled', 'True') == 'True'
            if not enabled:
                return message
        except AccessError:
            # If user can't read config parameters, assume disabled for security
            _logger.warning(f"User {self.env.user.login} cannot read auto email activity config - feature disabled")
            return message
            
        # Check if the user belongs to any of the configured groups
        if not self._user_in_configured_groups():
            return message
        
        # Check if we're in the correct application context (Helpdesk or Sales)
        current_model = self._name
        
        # Check if the model belongs to Helpdesk or Sales application
        is_helpdesk_model = self._is_helpdesk_model(current_model)
        is_sales_model = self._is_sales_model(current_model)
        
        if not (is_helpdesk_model or is_sales_model):
            return message
            
        # Check if this is an outgoing external email
        if not self._is_outgoing_external_email(message):
            return message
            
        # Check if user has permission to create activities on this record
        if not self._has_required_permissions():
            _logger.info(f"User {self.env.user.login} lacks permission to create activity on {self._name}:{self.id}")
            return message
            
        # Get recipients for activity summary
        external_emails = self._get_external_recipients(message)

        if not external_emails:
            return message
            
        # Create a completed activity
        try:
            # Use context to prevent recursive calls
            with_context = self.env.with_context(auto_email_activity_skip=True)
            activity_type = with_context.env.ref('mail.mail_activity_data_email')
            
            # Create and mark as done in one step
            activity_values = {
                'summary': _('Email sent to %s') % ', '.join(external_emails[:3]) + 
                          (', ...' if len(external_emails) > 3 else ''),
                'note': message.body or '',
                'activity_type_id': activity_type.id,
                'user_id': self.env.user.id,
                'res_model_id': self.env['ir.model']._get(self._name).id,
                'res_id': self.id,
                'date_deadline': fields.Date.today(),
            }
            
            activity = with_context.env['mail.activity'].create(activity_values)
            activity.action_done()
            
            _logger.info(f"Created completed email activity for message {message.id}")
            
        except Exception as e:
            _logger.error(f"Failed to create email activity: {str(e)}")
            # Don't raise exception, just log it - we don't want to interrupt the email flow
        
        return message
    
    def _is_outgoing_external_email(self, message):
        """Check if this is an outgoing email in a Helpdesk/Sales context."""
        if not message:
            return False
            
        # Must be an email message type
        if message.message_type != 'email':
            return False
        
        # Must have sender (outgoing)
        if not message.email_from:
            return False
            
        # Check if this message was created by the current user
        # (sender email might be overridden to department email)
        if message.author_id != self.env.user.partner_id:
            return False
        
        # Must have recipients
        if not message.partner_ids:
            return False
        
        return True
    
    def _get_external_recipients(self, message):
        """Get email recipients - simplified for Helpdesk/Sales context."""
        if not message or not message.partner_ids:
            return []
            
        recipient_emails = []
        
        for partner in message.partner_ids:
            # Skip internal users
            if partner.user_ids:
                continue
                
            email = partner.email or partner.name
            if email:
                recipient_emails.append(email)
        
        return recipient_emails
    
    def _user_in_configured_groups(self):
        """Check if current user belongs to any of the configured groups for auto email activities."""
        try:
            # Get all active group configurations
            active_group_configs = self.env['auto.email.group.config'].search([
                ('active', '=', True)
            ])
            
            if not active_group_configs:
                return False
            
            # Get the group IDs from the configurations
            configured_group_ids = active_group_configs.mapped('group_id.id')
            
            # Check if current user belongs to any of these groups
            user_group_ids = self.env.user.groups_id.ids
            
            # Return True if there's any intersection
            return bool(set(configured_group_ids) & set(user_group_ids))
            
        except Exception as e:
            _logger.warning(f"Error checking user groups for {self.env.user.login}: {str(e)}")
            return False
    
    def _has_required_permissions(self):
        """Check if user has permission to create activities on this record."""
        try:
            # User must have write access to the current record
            self.check_access_rights('write')
            self.check_access_rule('write')
            
            # Also check if user can create activities
            self.env['mail.activity'].check_access_rights('create')
            return True
        except AccessError:
            return False
        except Exception as e:
            _logger.warning(f"Permission check failed: {str(e)}")
            return False
        
    def _is_helpdesk_model(self, model_name):
        """Check if the model belongs to Helpdesk application."""
        if not model_name:
            return False
            
        helpdesk_models = [
            'helpdesk.ticket', 
            'helpdesk.team', 
            'helpdesk.tag',
            'helpdesk.stage',
            'helpdesk.ticket.type'
        ]
        return model_name in helpdesk_models
    
    def _is_sales_model(self, model_name):
        """Check if the model belongs to Sales application."""
        if not model_name:
            return False
            
        sales_models = [
            'sale.order',
            'sale.order.line',
            'sale.report',
            'crm.lead',
            'crm.team'
        ]
        return model_name in sales_models