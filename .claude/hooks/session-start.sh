#!/bin/bash
# Install the Python packages the test suite and check_integrity.py import,
# using the same version ranges as the GitHub Actions workflows.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

python3 -m pip install --quiet --disable-pip-version-check --root-user-action=ignore \
  pandas 'yfinance>=1.2.0' 'lxml>=5,<7' 'pypdf>=6,<7'
