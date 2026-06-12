# -*- coding: utf-8 -*-
################################################################################
#
#    Kolpolok Ltd. (https://www.kolpolok.com)
#    Author: Kolpolok (<https://www.kolpolok.com>)
#
################################################################################

{
    'name': "Custom Login Page",
    'version': '16.0.1.0',
    'live_test_url': 'https://youtu.be/mG5-_4KAbiw?si=6Ie7lQxgBxexqcKf',
    'summary': """This module assists in configuring a background image for the login page and hide other odoo elements""",
    'description': """Module helps to set background image in Login page.""",
    'license': 'LGPL-3',
    'website': "https://www.kolpoloktechnologies.com",
    'author': 'Kolpolok',
    'category': 'Tools',
    'depends': ['base', 'portal', 'web'],
    'data': [
        'views/res_company.xml',
        'views/web_login.xml',
        'views/logo_login.xml',
    ],
    'images': ['static/description/banner.png'],
    'sequence': 1,
    "application": True,
    "installable": True
}
