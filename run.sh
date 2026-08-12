#!/bin/bash
python3 compiler/tersec.py build examples/$1.te -o output/$1
./output/$1

