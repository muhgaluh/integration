# -*- coding: utf-8 -*-
{
    'name': "Opening Balance Batch Tool",  # Ganti Nama
    'summary': "Special tool for Opening Balance migration with Accounting Override",
    'author': "DPS-2025",
    'category': 'Warehouse',
    'version': '16.0.2.0.0',
    'depends': ['stock'],
    'data': [
        'security/stock_security.xml',
        'security/ir.model.access.csv',
        'views/generate_batches_wizard_views.xml',
        'views/stock_adjustment_batch_views.xml',
    ],
    'installable': True,
    'application': True,
}