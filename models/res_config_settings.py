from odoo import models, fields, api

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'
    
    auto_email_activity_enabled = fields.Boolean(
        string="Enable Auto Email Activity Creation",
        config_parameter='auto_email_activity_creation.enabled',
        default=True,
        help="If enabled, a completed activity will be created when users from sales or support groups "
             "send external emails through chatter in Helpdesk and Sales apps."
    )
    
    auto_email_for_sales = fields.Boolean(
        string="Create Activities for Sales Team",
        config_parameter='auto_email_activity_creation.for_sales',
        default=True,
        help="If enabled, activities will be created for Sales team members."
    )
    
    auto_email_for_support = fields.Boolean(
        string="Create Activities for Support Team",
        config_parameter='auto_email_activity_creation.for_support',
        default=True,
        help="If enabled, activities will be created for Support team members."
    )
