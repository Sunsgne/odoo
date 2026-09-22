{
    'name': 'ZENLENET 运营',
    'version': '19.0.1.0.0',
    'category': 'Sales',
    'summary': '客户、订单、出账，以及割接和维护通知',
    'author': 'ZENLENET PTE. LTD.',
    'license': 'LGPL-3',
    'depends': ['contacts', 'sale_management', 'account', 'mail', 'auth_oauth'],
    'data': [
        'security/ir.model.access.csv',
        'data/sequence.xml',
        'data/oauth_provider.xml',
        'views/maintenance_views.xml',
        'views/partner_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': True,
}
