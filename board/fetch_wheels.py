"""Download aarch64 / CPython 3.7 wheels into board/wheels for boards without internet (LubanCat Debian 10).

    python3 board/fetch_wheels.py        # run on the computer; deploy.sh does this automatically
"""

import json
import os
import re
import urllib.request

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wheels")
PKGS = {"pygame": "2.1.2", "aiohttp": "3.8.6", "multidict": "6.0.4", "yarl": "1.9.4", "frozenlist": "1.3.3",
        "aiosignal": "1.3.1", "async-timeout": "4.0.3", "asynctest": "0.13.0", "attrs": "23.1.0",
        "charset-normalizer": "3.3.2", "typing-extensions": "4.7.1", "idna": "3.7"}

os.makedirs(D, exist_ok=True)
for name, ver in PKGS.items():
    files = json.load(urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{ver}/json", timeout=30))["urls"]
    pick = [f for f in files if re.search(r"cp37-cp37m-manylinux[^-]*aarch64\.whl$", f["filename"])] or \
           [f for f in files if f["filename"].endswith("-none-any.whl")]
    out = os.path.join(D, pick[0]["filename"])
    if not os.path.exists(out):
        urllib.request.urlretrieve(pick[0]["url"], out)
    print("  wheel", pick[0]["filename"])
