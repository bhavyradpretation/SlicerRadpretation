"""Shared Qt stylesheets for Radpretation UI controls."""

# Accent used across the plugin (matches Studies refresh / login buttons)
ACCENT = "#007acc"
ACCENT_HOVER = "#0098ff"
SUCCESS = "#2e7d32"
SUCCESS_HOVER = "#43a047"
DANGER = "#c62828"
DANGER_HOVER = "#e53935"
WARNING = "#ef6c00"
WARNING_HOVER = "#ff9800"
MUTED = "#6b7280"

_BTN_BASE = """
    padding: 8px 12px;
    border-radius: 6px;
    font-weight: bold;
    font-size: 11px;
"""

PRIMARY_BUTTON = f"""
    QPushButton {{
        {_BTN_BASE}
        background-color: {ACCENT};
        color: white;
        border: none;
    }}
    QPushButton:hover {{
        background-color: {ACCENT_HOVER};
    }}
    QPushButton:pressed {{
        background-color: #005a9e;
    }}
"""

SECONDARY_BUTTON = f"""
    QPushButton {{
        {_BTN_BASE}
        background-color: rgba(0, 122, 204, 0.1);
        color: {ACCENT};
        border: 1px solid rgba(0, 122, 204, 0.35);
    }}
    QPushButton:hover {{
        background-color: rgba(0, 122, 204, 0.18);
    }}
"""

SUCCESS_BUTTON = f"""
    QPushButton {{
        {_BTN_BASE}
        background-color: {SUCCESS};
        color: white;
        border: none;
    }}
    QPushButton:hover {{
        background-color: {SUCCESS_HOVER};
    }}
"""

DANGER_BUTTON = f"""
    QPushButton {{
        {_BTN_BASE}
        background-color: {DANGER};
        color: white;
        border: none;
    }}
    QPushButton:hover {{
        background-color: {DANGER_HOVER};
    }}
"""

WARNING_BUTTON = f"""
    QPushButton {{
        {_BTN_BASE}
        background-color: {WARNING};
        color: white;
        border: none;
    }}
    QPushButton:hover {{
        background-color: {WARNING_HOVER};
    }}
"""

DISABLED_BUTTON = f"""
    QPushButton {{
        {_BTN_BASE}
        background-color: rgba(128, 128, 128, 0.12);
        color: {MUTED};
        border: 1px solid rgba(128, 128, 128, 0.25);
    }}
"""

ICON_TOOL_BUTTON = """
    QPushButton {
        background-color: rgba(128, 128, 128, 0.08);
        color: inherit;
        border: 1px solid rgba(128, 128, 128, 0.25);
        border-radius: 6px;
        font-weight: bold;
    }
    QPushButton:hover {
        background-color: rgba(128, 128, 128, 0.16);
        border-color: rgba(128, 128, 128, 0.4);
    }
    QPushButton:pressed {
        background-color: rgba(128, 128, 128, 0.22);
    }
"""

# Save Segmentation — original plugin colors (amber active, solid grey disabled)
SAVE_BUTTON_ENABLED = """
    QPushButton {
        background-color: #ffb74d;
        color: white;
        padding: 8px;
        border: none;
        border-radius: 6px;
        font-weight: bold;
        font-size: 11px;
    }
    QPushButton:hover {
        background-color: #ffa726;
    }
    QPushButton:pressed {
        background-color: #e65100;
    }
"""

SAVE_BUTTON_DISABLED = """
    QPushButton {
        background-color: #999999;
        color: white;
        padding: 8px;
        border-radius: 6px;
        font-size: 11px;
    }
"""

SAVE_BUTTON_EXPORTING = """
    QPushButton {
        background-color: #ef6c00;
        color: white;
        padding: 8px;
        border: none;
        border-radius: 6px;
        font-weight: bold;
        font-size: 11px;
    }
    QPushButton:disabled {
        background-color: #ef6c00;
        color: white;
    }
"""

SAVE_BUTTON_SUCCESS = """
    QPushButton {
        background-color: #009600;
        color: white;
        padding: 8px;
        border: none;
        border-radius: 6px;
        font-weight: bold;
        font-size: 11px;
    }
    QPushButton:disabled {
        background-color: #009600;
        color: white;
    }
"""

SAVE_BUTTON_FAILED = """
    QPushButton {
        background-color: #c62828;
        color: white;
        padding: 8px;
        border: none;
        border-radius: 6px;
        font-weight: bold;
        font-size: 11px;
    }
    QPushButton:disabled {
        background-color: #c62828;
        color: white;
    }
"""
