from odoo import models, api, fields, _
from odoo.exceptions import AccessError
import logging

_logger = logging.getLogger(__name__)

class SaleOrder(models.Model):
    _inherit = 'sale.order'
    
    def message_post(self, **kwargs):
        """Override message_post to create an activity when sending an external email via chatter."""
        
        # Call original method to create the message first
        message = super(SaleOrder, self).message_post(**kwargs)
        
        # Try to create activity for this message
        self._maybe_create_email_activity(message)
        
        return message
    
    def _maybe_create_email_activity(self, message):
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
        _logger.info(f"DEBUG: Message subtype = {message.subtype_id.name if message.subtype_id else 'None'}")
        _logger.info(f"DEBUG: Message email_from = {message.email_from}")
        _logger.info(f"DEBUG: Message partner_ids = {[p.name for p in message.partner_ids]}")
        _logger.info(f"DEBUG: Message author_id = {message.author_id.name if message.author_id else 'None'}")
        
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
        if not self._is_outgoing_external_message(message):
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
            
        # Create a completed activity
        try:
            _logger.info("DEBUG: Creating email activity...")
            
            # Use context to prevent recursive calls
            activity_type = self.env.ref('mail.mail_activity_data_email')
            
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
            
            # Create activity with context to prevent recursion
            activity = self.env['mail.activity'].with_context(auto_email_activity_skip=True).create(activity_values)
            activity.action_done()
            
            _logger.info(f"Successfully created completed email activity for message {message.id}")
            
        except Exception as e:
            _logger.error(f"Failed to create email activity: {str(e)}")
            # Don't raise exception, just log it - we don't want to interrupt the email flow
    
    def _is_outgoing_external_message(self, message):
        """Check if this is an outgoing message to external recipients."""
        if not message:
            return False
            
        # Check if this message was created by the current user
        if message.author_id != self.env.user.partner_id:
            _logger.info(f"DEBUG: Message author {message.author_id.name if message.author_id else 'None'} != current user {self.env.user.partner_id.name}")
            return False
        
        # For chatter messages, check if there are recipients in the message
        # Sometimes partners are in different fields or contexts
        has_recipients = False
        
        # Check partner_ids first
        if message.partner_ids:
            _logger.info(f"DEBUG: Found recipients in partner_ids: {[p.name for p in message.partner_ids]}")
            has_recipients = True
        
        # Also check if this is a "Send Message" action by looking at context or other indicators
        # Check if message has email_from (indicates external communication)
        if message.email_from and '@' in message.email_from:
            _logger.info(f"DEBUG: Message has email_from: {message.email_from}")
            has_recipients = True
        
        # Check the message body for email indicators or recipients
        if message.body and ('To:' in message.body or '@' in message.body):
            _logger.info("DEBUG: Message body contains recipient indicators")
            has_recipients = True
            
        # Check if this is related to a customer on the record
        if hasattr(self, 'partner_id') and self.partner_id:
            _logger.info(f"DEBUG: Record has customer: {self.partner_id.name}")
            has_recipients = True
            
        if not has_recipients:
            _logger.info("DEBUG: No recipients found anywhere")
            return False
            
        # Accept comment messages (chatter "Send Message") and email messages
        if message.message_type == 'comment':
            # Check if subtype suggests external communication
            if message.subtype_id and message.subtype_id.name:
                subtype_name = message.subtype_id.name
                _logger.info(f"DEBUG: Comment message with subtype: {subtype_name}")
                
                # Accept various subtypes that indicate external communication
                external_subtypes = ['Discussions', 'Note', 'Email', 'Message']
                if subtype_name in external_subtypes:
                    return True
            
            # If no specific subtype, assume it's external if it has recipients
            return True
            
        # Also accept actual email messages
        if message.message_type == 'email':
            _logger.info("DEBUG: Email message type")
            return True
        
        _logger.info(f"DEBUG: Message type '{message.message_type}' not recognized as outgoing")
        return False
    
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
        
        # If no partners found, try to get recipient from the record's customer
        if not recipient_emails and hasattr(self, 'partner_id') and self.partner_id:
            partner = self.partner_id
            # Skip if this partner is an internal user
            if not partner.user_ids:
                email = partner.email or partner.name
                if email:
                    recipient_emails.append(email)
                    _logger.info(f"DEBUG: Added record customer as recipient: {email}")
        
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


class CrmLead(models.Model):
    _inherit = 'crm.lead'
    
    def message_post(self, **kwargs):
        """Override message_post to create an activity when sending an external email via chatter."""
        
        # Call original method to create the message first
        message = super(CrmLead, self).message_post(**kwargs)
        
        # Try to create activity for this message
        self._maybe_create_email_activity(message)
        
        return message
    
    def _maybe_create_email_activity(self, message):
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
        _logger.info(f"DEBUG: Message subtype = {message.subtype_id.name if message.subtype_id else 'None'}")
        _logger.info(f"DEBUG: Message email_from = {message.email_from}")
        _logger.info(f"DEBUG: Message partner_ids = {[p.name for p in message.partner_ids]}")
        _logger.info(f"DEBUG: Message author_id = {message.author_id.name if message.author_id else 'None'}")
        
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
        if not self._is_outgoing_external_message(message):
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
            
        # Create a completed activity
        try:
            _logger.info("DEBUG: Creating email activity...")
            
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
            
            _logger.info(f"Successfully created completed email activity for message {message.id}")
            
        except Exception as e:
            _logger.error(f"Failed to create email activity: {str(e)}")
            # Don't raise exception, just log it - we don't want to interrupt the email flow
    
    def _is_outgoing_external_message(self, message):
        """Check if this is an outgoing message to external recipients."""
        if not message:
            return False
            
        # Check if this message was created by the current user
        if message.author_id != self.env.user.partner_id:
            _logger.info(f"DEBUG: Message author {message.author_id.name if message.author_id else 'None'} != current user {self.env.user.partner_id.name}")
            return False
        
        # Must have recipients
        if not message.partner_ids:
            _logger.info("DEBUG: No partner recipients")
            return False
            
        # Check if it's a comment (chatter message) - this is what "Send Message" creates
        if message.message_type == 'comment' and message.subtype_id:
            subtype_name = message.subtype_id.name or ''
            _logger.info(f"DEBUG: Comment message with subtype: {subtype_name}")
            # Accept comments that are likely to be external communications
            return True
            
        # Also accept actual email messages
        if message.message_type == 'email':
            _logger.info("DEBUG: Email message type")
            return True
        
        _logger.info(f"DEBUG: Message type '{message.message_type}' not recognized as outgoing")
        return False
    
    def _get_external_recipients(self, message):
        """Get email recipients - exclude internal users."""
        if not message or not message.partner_ids:
            return []
            
        recipient_emails = []
        
        for partner in message.partner_ids:
            # Skip internal users
            if partner.user_ids:
                _logger.info(f"DEBUG: Skipping internal user {partner.name}")
                continue
                
            email = partner.email or partner.name
            if email:
                recipient_emails.append(email)
                _logger.info(f"DEBUG: Added external recipient {partner.name}")
        
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


class HelpdeskTicket(models.Model):
    _inherit = 'helpdesk.ticket'
    
    def message_post(self, **kwargs):
        """Override message_post to create an activity when sending an external email via chatter."""
        
        # Call original method to create the message first
        message = super(HelpdeskTicket, self).message_post(**kwargs)
        
        # Try to create activity for this message
        self._maybe_create_email_activity(message)
        
        return message
    
    def _maybe_create_email_activity(self, message):
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
        _logger.info(f"DEBUG: Message subtype = {message.subtype_id.name if message.subtype_id else 'None'}")
        _logger.info(f"DEBUG: Message email_from = {message.email_from}")
        _logger.info(f"DEBUG: Message partner_ids = {[p.name for p in message.partner_ids]}")
        _logger.info(f"DEBUG: Message author_id = {message.author_id.name if message.author_id else 'None'}")
        
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
        if not self._is_outgoing_external_message(message):
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
            
        # Create a completed activity
        try:
            _logger.info("DEBUG: Creating email activity...")
            
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
            
            _logger.info(f"Successfully created completed email activity for message {message.id}")
            
        except Exception as e:
            _logger.error(f"Failed to create email activity: {str(e)}")
            # Don't raise exception, just log it - we don't want to interrupt the email flow
    
    def _is_outgoing_external_message(self, message):
        """Check if this is an outgoing message to external recipients."""
        if not message:
            return False
            
        # Check if this message was created by the current user
        if message.author_id != self.env.user.partner_id:
            _logger.info(f"DEBUG: Message author {message.author_id.name if message.author_id else 'None'} != current user {self.env.user.partner_id.name}")
            return False
        
        # Must have recipients
        if not message.partner_ids:
            _logger.info("DEBUG: No partner recipients")
            return False
            
        # Check if it's a comment (chatter message) - this is what "Send Message" creates
        if message.message_type == 'comment' and message.subtype_id:
            subtype_name = message.subtype_id.name or ''
            _logger.info(f"DEBUG: Comment message with subtype: {subtype_name}")
            # Accept comments that are likely to be external communications
            return True
            
        # Also accept actual email messages
        if message.message_type == 'email':
            _logger.info("DEBUG: Email message type")
            return True
        
        _logger.info(f"DEBUG: Message type '{message.message_type}' not recognized as outgoing")
        return False
    
    def _get_external_recipients(self, message):
        """Get email recipients - exclude internal users."""
        if not message or not message.partner_ids:
            return []
            
        recipient_emails = []
        
        for partner in message.partner_ids:
            # Skip internal users
            if partner.user_ids:
                _logger.info(f"DEBUG: Skipping internal user {partner.name}")
                continue
                
            email = partner.email or partner.name
            if email:
                recipient_emails.append(email)
                _logger.info(f"DEBUG: Added external recipient {partner.name}")
        
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