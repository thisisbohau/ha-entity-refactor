"""Constants for the Entity ID Renamer integration."""

from __future__ import annotations

DOMAIN = "entity_renamer"
VERSION = "1.0.0"

PANEL_URL_PATH = "entity-renamer"
PANEL_TITLE = "Entity Renamer"
PANEL_ICON = "mdi:rename-box"
PANEL_NAME = "entity-renamer-panel"
STATIC_URL = "/entity_renamer_static"

BACKUP_DIR = "entity_renamer_backups"
BACKUP_KEEP = 20

# Maximum size of a YAML file we are willing to read into memory (bytes).
MAX_FILE_SIZE = 8 * 1024 * 1024

# Directories under /config that are never scanned or rewritten.
EXCLUDE_DIRS = frozenset(
    {
        ".storage",
        ".cloud",
        ".git",
        ".venv",
        "__pycache__",
        "backups",
        "blueprints",
        "custom_components",
        "deps",
        "node_modules",
        "tts",
        "image",
        "www",
        BACKUP_DIR,
    }
)

# Files under /config that are never rewritten even though they are YAML.
EXCLUDE_FILES = frozenset({"secrets.yaml", "known_devices.yaml"})

YAML_SUFFIXES = (".yaml", ".yml")

# Preferred reload after an apply: one service that reloads every YAML-backed
# domain that supports it, including input_*, counter and timer, which the
# explicit list below would miss.
RELOAD_ALL_SERVICE = ("homeassistant", "reload_all")

# Fallback for cores without reload_all, and for core config (customize.yaml),
# which reload_all does not cover.
RELOAD_SERVICES = (
    ("automation", "reload"),
    ("script", "reload"),
    ("scene", "reload"),
    ("template", "reload"),
    ("homeassistant", "reload_core_config"),
)

# Sentinel used by the frontend for the default (unnamed) Lovelace dashboard.
DEFAULT_DASHBOARD_KEY = "__default__"
