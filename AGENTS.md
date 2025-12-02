# AGENT GUIDELINES

- Use hidden attributes (prefixed with `_`) and expose getters unless a value must be modifiable from outside the class.
- Stick to DRY, KISS, and YAGNI principles; avoid duplicating code, and extend existing helpers when adding functionality.
- Assume configuration files are already migrated; do not add fallback defaults in code paths that read config values.
- Default workflow for config-related changes: add migration → update UI → update code. Skip the first two steps only when no config change is involved.
