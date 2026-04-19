from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _expand_env(raw: str) -> str:
    def replace(match: re.Match[str]) -> str:
        return os.getenv(match.group(1), "")

    return ENV_PATTERN.sub(replace, raw)


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    raw = config_path.read_text(encoding="utf-8")
    expanded = _expand_env(raw)
    data = yaml.safe_load(expanded) or {}
    if not isinstance(data, dict):
        raise ValueError("Config root must be a mapping")
    return data
