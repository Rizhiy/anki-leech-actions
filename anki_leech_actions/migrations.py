"""Configuration schema migrations for Anki Leech Actions."""

from __future__ import annotations

from typing import Any, Callable

MigrationFunction = Callable[[dict[str, Any]], dict[str, Any]]


def v1(config: dict[str, Any]) -> dict[str, Any]:
    """Introduce schema_version and ensure base keys exist."""

    config.setdefault("leech_tag", "leech")
    rules = config.get("rules")
    if not isinstance(rules, list):
        rules = []
    config["rules"] = rules
    config.setdefault("auto_run_enabled", True)
    config["schema_version"] = 1
    return config


def v2(config: dict[str, Any]) -> dict[str, Any]:
    """Ensure auto_run_enabled flag exists after schema v1 installs."""

    config.setdefault("auto_run_enabled", True)
    config["schema_version"] = 2
    return config




def v3(config: dict[str, Any]) -> dict[str, Any]:
    """Add optional notification toggle for auto processing."""

    config.setdefault("show_auto_notifications", True)
    config["schema_version"] = 3
    return config


MIGRATIONS: list[MigrationFunction] = [v1, v2, v3]
CURRENT_SCHEMA_VERSION = len(MIGRATIONS)


def run_migrations(config: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Apply migrations only when the stored schema is outdated."""

    version = config.get("schema_version") or 0
    try:
        current_version = int(version)
    except (TypeError, ValueError):
        current_version = 0

    updated = False
    for target_version, migration in enumerate(MIGRATIONS, start=1):
        if current_version < target_version:
            config = migration(config)
            current_version = target_version
            updated = True

    return config, updated
