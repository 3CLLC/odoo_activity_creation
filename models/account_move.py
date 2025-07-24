from odoo import models, api, fields, _
from odoo.exceptions import AccessError
from markupsafe import Markup
import logging

_logger = logging.getLogger(__name__)

class AccountMove(models.Model):
    _inherit = 'account.move'
    
    def message_post(self, *args, **kwargs):
        """Override message_post to create an activity when sending an external email via chatter."""
        
        subtype_xmlid = kwargs.get('subtype_xmlid')

        # Call original method to create the message first
        message = super(AccountMove, self).message_post(*args, **kwargs)
        
        # Try to create activity for this message
        self._maybe_create_email_activity(message, subtype_xmlid)
        
        return message
    
    def _maybe_create_email_activity(self, message, subtype_xmlid):
        """Check if we should create an email activity and create it if appropriate."""
        
        _logger.info(f"=== DEBUG: Checking message {message.id if message else 'None'} on {self._name}:{self.id} ===")
        
        # Skip processing if this is a recursive call or system-generated message
        if self.env.context.get('auto_email_activity_skip'):
            _logger.info("DEBUG: Skipping due to context flag")
            return
            
        if not message:
            _logger.info("DEBUG: No message created")
            return
            
        _logger.info(f"DEBUG: Message type = {message.message_type}")
        _logger.info(f"DEBUG: Message subtype = {subtype_xmlid if subtype_xmlid else 'None'}")
        _logger.info(f"DEBUG: Message email_from = {message.email_from}")
        _logger.info(f"DEBUG: Message partner_ids = {[p.name for p in message.partner_ids]}")
        _logger.info(f"DEBUG: Message author_id = {message.author_id.name if message.author_id else 'None'}")
        
        # Only process customer invoices and credit notes
        if self.move_type not in ['out_invoice', 'out_refund']:
            _logger.info(f"DEBUG: Skipping non-customer invoice type: {self.move_type}")
            return
        
        # Check if feature is enabled
        try:
            enabled = self.env['ir.config_parameter'].get_param('auto_email_activity_creation.enabled', 'True') == 'True'
            if not enabled:
                _logger.info("DEBUG: Feature disabled")
                return
        except AccessError:
            _logger.warning(f"User {self.env.user.login} cannot read auto email activity config - feature disabled")
            return
            
        # Check if the user belongs to any of the configured groups
        if not self._user_in_configured_groups():
            _logger.info("DEBUG: User not in configured groups")
            return
            
        # Check if this is an outgoing message to external recipients
        if not self._is_outgoing_external_message(message, subtype_xmlid):
            _logger.info("DEBUG: Not an outgoing external message")
            return
            
        # Check if user has permission to create activities on this record
        if not self._has_required_permissions():
            _logger.info(f"User {self.env.user.login} lacks permission to create activity on {self._name}:{self.id}")
            return
            
        # Get recipients for activity summary
        external_emails = self._get_external_recipients(message)

        if not external_emails:
            _logger.info("DEBUG: No external recipients found")
            return
            
        # Create a completed activity using custom approach
        try:
            _logger.info("DEBUG: Creating email activity...")
            
            # Get the email activity type and ensure it keeps done activities
            activity_type = self.env.ref('mail.mail_activity_data_email')
            
            # Ensure the activity type is configured to keep done activities
            if not activity_type.keep_done:
                activity_type.sudo().write({'keep_done': True})
            
            # Step 1: Create the activity normally (will be active/todo initially)
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
            
            # Create activity with context to prevent recursion
            activity = self.env['mail.activity'].with_context(auto_email_activity_skip=True).create(activity_values)
            
            _logger.info(f"DEBUG: Created activity {activity.id}, now marking as done manually...")
            
            # Step 2: Manually mark as done
            # Archive the activity manually (this is what action_done() does internally)
            activity.with_context(auto_email_activity_skip=True).write({
                'active': False,
                'date_done': fields.Datetime.now()
            })
            
            # Step 3: Post our own custom internal note as OdooBot
            # Get OdooBot user
            odoobot_user = self.env.ref('base.user_root')

            # Create the custom message body
            translated_message = _(
                "<p>Email activity auto-completed for <strong>%s</strong>!</p>"
            ) % (
                self.env.user.name
            )

            custom_body = Markup(translated_message)
            
            self.with_context(auto_email_activity_skip=True, mail_create_nosubscribe=True).message_post(
                body=custom_body,
                message_type='notification',
                subtype_xmlid='mail.mt_note',  # Internal note
                author_id=odoobot_user.partner_id.id,  # Post as OdooBot
            )
            
            _logger.info(f"Successfully created and completed email activity for message {message.id}")
            
        except Exception as e:
            _logger.error(f"Failed to create email activity: {str(e)}")
            # Don't raise exception, just log it - we don't want to interrupt the email flow
    
    def _is_outgoing_external_message(self, message, subtype_xmlid):
        """Check if this is an outgoing message to external recipients."""
        if not message:
            return False
            
        # Check if this message was created by the current user
        if message.author_id != self.env.user.partner_id:
            _logger.info(f"DEBUG: Message author {message.author_id.name if message.author_id else 'None'} != current user {self.env.user.partner_id.name}")
            return False
        
        # Check if this is a customer message using message type
        is_customer_message = subtype_xmlid == 'mail.mt_comment'
        
        _logger.info(f"DEBUG: Is customer message: {is_customer_message}")
        
        return is_customer_message
    
    def _get_external_recipients(self, message):
        """Get email recipients - exclude internal users."""
        recipient_emails = []
        
        # First, try to get recipients from partner_ids
        if message and message.partner_ids:
            for partner in message.partner_ids:
                # Skip internal users
                if partner.user_ids:
                    _logger.info(f"DEBUG: Skipping internal user {partner.name}")
                    continue
                    
                email = partner.email or partner.name
                if email:
                    recipient_emails.append(email)
                    _logger.info(f"DEBUG: Added external recipient {email}")
        
        # If no partners found, try to get recipient from the invoice's customer
        if not recipient_emails and self.partner_id:
            partner = self.partner_id
            # Skip if this partner is an internal user
            if not partner.user_ids:
                email = partner.email or partner.name
                if email:
                    recipient_emails.append(email)
                    _logger.info(f"DEBUG: Added invoice customer as recipient: {email}")
        
        # If still no recipients, try to extract from email_from (for display purposes)
        if not recipient_emails and message and message.email_from:
            # This is a fallback - we assume if there's an email_from, there was a recipient
            recipient_emails.append("External Contact")
            _logger.info(f"DEBUG: Using fallback recipient indicator")
        
        return recipient_emails
    
    def _user_in_configured_groups(self):
        """Check if current user belongs to any of the configured groups for auto email activities."""
        try:
            # Get all active group configurations
            active_group_configs = self.env['auto.email.group.config'].search([
                ('active', '=', True)
            ])
            
            if not active_group_configs:
                _logger.info("DEBUG: No active group configurations found")
                return False
            
            # Get the group IDs from the configurations
            configured_group_ids = active_group_configs.mapped('group_id.id')
            _logger.info(f"DEBUG: Configured group IDs: {configured_group_ids}")
            
            # Check if current user belongs to any of these groups
            user_group_ids = self.env.user.groups_id.ids
            _logger.info(f"DEBUG: User group IDs: {user_group_ids}")
            
            # Return True if there's any intersection
            intersection = set(configured_group_ids) & set(user_group_ids)
            result = bool(intersection)
            _logger.info(f"DEBUG: User in configured groups: {result} (intersection: {intersection})")
            return result
            
        except Exception as e:
            _logger.warning(f"Error checking user groups for {self.env.user.login}: {str(e)}")
            return False
    
    def _has_required_permissions(self):
        """Check if user has permission to create activities on this record."""
        try:
            # User must have write access to the current record (Odoo 18 syntax)
            self.check_access('write')
            
            # Also check if user can create activities (Odoo 18 syntax)
            self.env['mail.activity'].check_access('create')
            return True
        except AccessError:
            return False
        except Exception as e:
            _logger.warning(f"Permission check failed: {str(e)}")
            return False