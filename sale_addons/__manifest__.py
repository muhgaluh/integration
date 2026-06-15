{
    'name': 'Sale Stock Availability Status',
    'version': '16.0.1.0.0',
    'category': 'Sales',
    'summary': 'Show Stock Availability Status on Sales Order',
    'author': 'Module',
    'depends': [
        'sale_management',
        'stock'
    ],
    'data': [
        'views/sale_order_views.xml',
    ],
    'installable': True,
    'application': False,
}