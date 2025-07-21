# Auto Email Activity Creation

## Summary
This Odoo 18.0 module automatically creates a completed activity record when users from specific groups (sales and support) send external emails through the chatter interface in Helpdesk and Sales applications.

## Purpose
Track all external communications initiated by sales and support teams without requiring manual activity logging. This provides a comprehensive communication history directly in the activity view.

## Features
- **Automatic Activity Creation**: Creates a completed activity entry when an external email is sent
- **User Group Specific**: Only applies to users in sales and support groups
- **Application Specific**: Only works in Helpdesk and Sales applications
- **Configurable**: Enable/disable the feature through settings
- **Zero User Interaction**: Works silently in the background

## Configuration
1. Install the module
2. Go to Settings → General Settings → Auto Email Activity
3. Configure the following options:
   - Enable/disable the feature globally
   - Enable/disable for Sales team members
   - Enable/disable for Support team members

## Technical Implementation
- Extends the `mail.thread` model to intercept message posting
- Identifies external emails being sent from Helpdesk and Sales apps
- Verifies user belongs to the appropriate groups
- Creates and marks as complete an email activity record

## Dependencies
- mail
- helpdesk
- sale
- sale_management