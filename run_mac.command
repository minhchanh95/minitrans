#!/bin/bash
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || ./setup_mac.sh || exit 1
exec .venv/bin/python run.py
