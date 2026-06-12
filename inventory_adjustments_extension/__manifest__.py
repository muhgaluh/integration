# -*- coding: utf-8 -*-
{
    'name': "Inventory Adjustments Extension",
    'summary': """
        Enhances inventory adjustments with batching for better auditing.""",
    'author': "DPS-2025",
    'category': 'Warehouse',
    'version': '16.0.1.1.0',
    'depends': ['stock'],
    'data': [
        'security/ir.model.access.csv',
        'views/generate_batches_wizard_views.xml',
        'views/stock_adjustment_batch_views.xml',
    ],
    'installable': True,
    'application': True,
}