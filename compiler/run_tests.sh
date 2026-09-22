#!/bin/bash
set -e
cd "$(dirname "$0")/.."
python3 -m unittest compiler.test_compiler -v
