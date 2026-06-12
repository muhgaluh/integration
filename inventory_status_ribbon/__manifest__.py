{
    'name': 'Stock Picking Ribbon',
    'version': '16.0.1.0.0',
    'category': 'Inventory',
    'summary': 'Add ribbon status on Inventory Transfers',
    'author': 'Galuh Dev',
    'depends': [
        'stock',
        'web',
    ],
    'data': [
        'views/stock_picking_views.xml',
    ],
    # Css dan asset lain
    'assets': {
        'web.assets_backend': [
            'ribbon_add_inv/static/src/css/ribbon.css',
        ],
    },
    'installable': True,
    'application': False,
}