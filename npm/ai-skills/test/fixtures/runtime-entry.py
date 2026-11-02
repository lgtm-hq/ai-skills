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
elif sys.argv[1:] == ["signal"]:
    print("ready", flush=True)
    while True:
        time.sleep(1)
elif sys.argv[1:] == ["self-signal"]:
    os.kill(os.getpid(), signal.SIGTERM)
else:
    print(json.dumps(sys.argv[1:], ensure_ascii=False))
    print("fixture stderr", file=sys.stderr)
    sys.exit(23)
