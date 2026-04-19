#!/usr/bin/env bash
set -euo pipefail

export PYTHONPATH="${PYTHONPATH:-src}"
python3 main.py --config "${1:-config/config.yml}" --once
