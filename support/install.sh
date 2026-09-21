#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
venv_path="$repo_root/.venv"

if [ -x "$venv_path/Scripts/python.exe" ]; then
    python_path="$venv_path/Scripts/python.exe"
else
    python_path="$venv_path/bin/python"
fi

if [ ! -x "$python_path" ]; then
    uv venv "$venv_path" --python 3.12
    if [ -x "$venv_path/Scripts/python.exe" ]; then
        python_path="$venv_path/Scripts/python.exe"
    fi
fi

uv pip install --python "$python_path" sqlite-rx
printf 'Installed sqlite-rx in %s\n' "$venv_path"
printf 'Run: %s support/sqliteserver.py\n' "$python_path"
