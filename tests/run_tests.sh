#!/bin/bash
set -e
cd "$(dirname "$0")/.."
python3 -m unittest tests.test_compiler -v
