from odoo import models, api, fields, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class MailThread(models.AbstractModel):
    _inherit = 'mail.thread'
    
    @api.returns('mail.message', lambda value: value.id)
    def message_post(self, **kwargs):
        """Override message_post to create an activity when sending an external email via chatter."""
        
        # Call original method to create the message
        message = super(MailThread, self).message_post(**kwargs)
        
        # Check if feature is enabled
        if not self.env['ir.config_parameter'].sudo().get_param('auto_email_activity_creation.enabled', 'True') == 'True':
            return message
            
        # Only proceed if this is an email message being sent to external recipients
        if (message.message_type == 'email' and 
            message.email_from and 
            (message.recipient_ids or message.partner_ids) and 
            not message.is_internal):
            
            # Check if the user belongs to sales or support groups
            user = self.env.user
            is_sales = user.has_group('sales_team.group_sale_salesman') or user.has_group('sales_team.group_sale_manager')
            is_support = user.has_group('helpdesk.group_helpdesk_user') or user.has_group('helpdesk.group_helpdesk_manager')
            
            # Check group settings
            sales_enabled = self.env['ir.config_parameter'].sudo().get_param('auto_email_activity_creation.for_sales', 'True') == 'True'
            support_enabled = self.env['ir.config_parameter'].sudo().get_param('auto_email_activity_creation.for_support', 'True') == 'True'
            
            if not ((is_sales and sales_enabled) or (is_support and support_enabled)):
                return message
            
            # Check if we're in the correct application context (Helpdesk or Sales)
            current_model = self._name
            
            # Check if the model belongs to Helpdesk or Sales application
            is_helpdesk_model = self._is_helpdesk_model(current_model)
            is_sales_model = self._is_sales_model(current_model)
            
            if not (is_helpdesk_model or is_sales_model):
                return message
                
            # Get external recipients for activity summary
            recipient_emails = []
            for partner in message.partner_ids:
                if not partner.user_ids:  # External partner without user account
                    recipient_emails.append(partner.email or partner.name)
            
            if not recipient_emails:
                return message
                
            # Create a completed activity
            try:
                activity_type = self.env.ref('mail.mail_activity_data_email')
                
                # Create and mark as done in one step
                activity_values = {
                    'summary': _('Email sent to %s') % ', '.join(recipient_emails[:3]) + 
                              (', ...' if len(recipient_emails) > 3 else ''),
                    'note': message.body,
                    'activity_type_id': activity_type.id,
                    'user_id': self.env.user.id,
                    'res_model_id': self.env['ir.model']._get(self._name).id,
                    'res_id': self.id,
                    'date_deadline': fields.Date.today(),
                }
                
                activity = self.env['mail.activity'].create(activity_values)
                activity.action_done()
                
                _logger.info(f"Created completed email activity for message {message.id}")
                
            except Exception as e:
                _logger.error(f"Failed to create email activity: {str(e)}")
                # Don't raise exception, just log it - we don't want to interrupt the email flow
        
        return message
        
    def _is_helpdesk_model(self, model_name):
        """Check if the model belongs to Helpdesk application."""
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
        sales_models = [
            'sale.order',
            'sale.order.line',
            'sale.report',
            'crm.lead',
            'crm.team'
        ]
        return model_name in sales_models
