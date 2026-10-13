"""OCOBot navigation screen registry (T10b).

The five structural placeholder screens of the nav-shell, in mockup order.
Each entry exposes:
- ``key``: stable identifier used by the router (verbatim mockup file stem).
- ``nav_label``: sidebar entry wording (verbatim from docs/ui_mockups).
- ``icon``: sidebar glyph (verbatim from the mockup nav).
- ``title``: Topbar title for that screen (verbatim mockup ``<h1>``).

No business logic, no content — placeholders only (real content is T11–T13).
"""

# Order and wording are verbatim from docs/ui_mockups (sidebar nav + topbar h1).
SCREENS = [
    {
        "key": "01_dashboard",
        "nav_label": "لوحة التحكم",
        "icon": "▦",
        "title": "لوحة التحكم",
    },
    {
        "key": "02_open_orders",
        "nav_label": "الأوامر المفتوحة",
        "icon": "▤",
        "title": "الأوامر المفتوحة",
    },
    {
        "key": "03_selected_and_edit",
        "nav_label": "تفاصيل وتعديل",
        "icon": "✎",
        "title": "تفاصيل الأمر والتعديل اليدوي",
    },
    {
        "key": "04_dynamic_monitoring",
        "nav_label": "المراقبة الديناميكية",
        "icon": "◎",
        "title": "المراقبة الديناميكية",
    },
    {
        "key": "05_safe_execution",
        "nav_label": "التنفيذ الآمن",
        "icon": "⚡",
        "title": "التنفيذ الآمن",
    },
    {
        "key": "06_demo",
        "nav_label": "وضع العرض",
        "icon": "▶",
        "title": "وضع العرض (Demo)",
    },
    {
        "key": "07_connection",
        "nav_label": "الاتصال",
        "icon": "⇄",
        "title": "الاتصال بالحساب",
    },
    {
        "key": "08_completed_trades",
        "nav_label": "الصفقات المنتهية",
        "icon": "✔",
        "title": "الصفقات المنتهية",
    },
    {
        "key": "09_alerts",
        "nav_label": "تنبيهات Telegram",
        "icon": "✉",
        "title": "تنبيهات Telegram",
    },
]

__all__ = ["SCREENS"]
