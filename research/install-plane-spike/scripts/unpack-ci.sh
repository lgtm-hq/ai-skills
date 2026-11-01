#!/usr/bin/env bash
set -euo pipefail
mkdir -p build/spike/ts build/spike/py
tar -xzf build/spike/ts.tgz -C build/spike/ts --strip-components=1
tar -xzf build/spike/py.tgz -C build/spike/py --strip-components=1
