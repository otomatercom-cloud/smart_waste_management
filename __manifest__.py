# Part of Otomater. See LICENSE file for full copyright and licensing details.
{
    'name': 'Smart Street Waste Management & Notification System',
    'version': '19.0.1.0.0',
    'category': 'Operations/Field Service',
    'summary': 'IoT smart waste bin monitoring, collection workflow, '
               'escalations and Telegram notifications',
    'description': """
Otomater Smart Street Waste Management & Notification System
============================================================
Central management platform for an IoT-based smart waste collection
solution: ESP32 ultrasonic fill-level sensors, automatic full/empty
triggers, collection requests, configurable escalation rules, Telegram
notifications with QR-based member registration, role-based portal,
public bin QR status pages, complaints and collection history.
""",
    'author': 'Otomater',
    'company': 'Otomater',
    'website': 'https://otomater.com',
    'license': 'OPL-1',
    'depends': ['base', 'mail', 'portal', 'web'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'security/record_rules.xml',
        'data/sequences.xml',
        'data/notification_data.xml',
        'data/cron.xml',
        'views/geography_views.xml',
        'views/association_views.xml',
        'views/street_views.xml',
        'views/bin_views.xml',
        'views/sensor_reading_views.xml',
        'views/collection_views.xml',
        'views/staff_views.xml',
        'views/complaint_views.xml',
        'views/notification_views.xml',
        'views/telegram_views.xml',
        'views/settings_views.xml',
        'views/dashboard_views.xml',
        'views/menus.xml',
        'views/portal_templates.xml',
        'views/public_templates.xml',
    ],
    'demo': [
        'demo/demo_data.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'smart_waste_management/static/src/css/swm_dashboard.css',
            'smart_waste_management/static/src/js/swm_dashboard.js',
            'smart_waste_management/static/src/xml/swm_dashboard.xml',
        ],
        'web.assets_frontend': [
            'smart_waste_management/static/src/css/swm_portal.css',
        ],
    },
    'application': True,
    'installable': True,
}
