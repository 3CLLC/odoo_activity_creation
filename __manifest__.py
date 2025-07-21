{
    'name': 'Auto Email Activity Creation',
    'version': '1.0',
    'category': 'Productivity/Emails',
    'summary': 'Automatically create completed activities for external emails',
    'description': """
        This module automatically creates a completed activity when users send 
        external emails through chatter in Helpdesk and Sales apps.
        
        Features:
        - Automatically tracks external emails sent via chatter
        - Creates completed activities for tracking purposes
        - Configurable for specific user groups (sales and support)
        - Only works in Helpdesk and Sales applications
    """,
    'author': 'Patrick Kozlowski',
    'website': 'https://www.3chi.com',
    'depends': ['mail', 'account' 'helpdesk', 'sale', 'sale_management'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
