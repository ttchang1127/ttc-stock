#!/bin/bash
# Install the Python packages from requirements.txt, the same file every
# GitHub Actions workflow installs, so tests and check_integrity.py run.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

python3 -m pip install --quiet --disable-pip-version-check --root-user-action=ignore \
  -r "${CLAUDE_PROJECT_DIR:-.}/requirements.txt"
