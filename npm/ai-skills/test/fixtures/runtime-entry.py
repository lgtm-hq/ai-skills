"""Injected payload used only to exercise the launcher process contract."""

import json
import os
import signal
import sys
import time

if sys.argv[1:] == ["--version"]:
    print("fixture-engine 1.2.3")
elif sys.argv[1:] == ["list"]:
    print("fixture-plugin\tfixture-skill")
elif sys.argv[1:] == ["stdin"]:
    sys.stdout.write(sys.stdin.read())
elif sys.argv[1:] == ["signal"]:
    print(f"ready:{os.getpid()}", flush=True)
    while True:
        time.sleep(1)
elif sys.argv[1:2] == ["self-signal"]:
    selected = getattr(signal, sys.argv[2])
    signal.signal(selected, signal.SIG_DFL)
    print(os.getpid(), flush=True)
    print("fixture signal stderr", file=sys.stderr, flush=True)
    os.kill(os.getpid(), selected)
else:
    print(json.dumps(sys.argv[1:], ensure_ascii=False))
    print("fixture stderr", file=sys.stderr)
    sys.exit(23)
