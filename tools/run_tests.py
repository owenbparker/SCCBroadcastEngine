"""Runs every test: SCC Broadcast Engine's own (tests/) and each part's own
tests (apps/<part>/tests), each in its own Python so they can't trip over
one another. Exit code 1 if any fail.

    python tools/run_tests.py            everything
    python tools/run_tests.py shell lolhud
"""

import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPS = os.path.join(ROOT, "apps")


def main(names):
    folders = sorted(d for d in os.listdir(APPS) if os.path.isdir(os.path.join(APPS, d, "tests")))
    suites = [("shell", ROOT)] + [(d, os.path.join(APPS, d)) for d in folders]
    if names:
        suites = [s for s in suites if s[0] in names]
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([ROOT] + [os.path.join(APPS, d) for d in os.listdir(APPS)
                                                                 if os.path.isdir(os.path.join(APPS, d))]))
    failed = []
    for name, cwd in suites:
        t0 = time.monotonic()
        print(f"=== {name}", flush=True)
        r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=cwd, env=env)
        print(f"=== {name}: {'OK' if r.returncode == 0 else 'FAILED'} ({time.monotonic() - t0:.0f} s)", flush=True)
        if r.returncode:
            failed.append(name)
    print("All tests passed" if not failed else f"Failed: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
