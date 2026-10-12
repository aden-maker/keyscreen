"""Register a running KeyScreen (board or sim) as an Agnes MHS device so the Agnes model can drive it.

    uv run --project <agnes_mhs> python mhs_device.py [ws://127.0.0.1:8800] [--board http://127.0.0.1:8765]
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any

from agnes_mhs import Device
from agnes_mhs.device import CallError

BOARD = "http://127.0.0.1:8765"


def api(method: str, path: str, body: dict | None = None) -> Any:
    req = urllib.request.Request(BOARD + path, method=method, data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        data = r.read()
        return json.loads(data) if r.headers.get_content_type() == "application/json" else data


async def call(method: str, path: str, body: dict | None = None) -> Any:
    try:
        return await asyncio.to_thread(api, method, path, body)
    except urllib.error.HTTPError as e:
        raise CallError("failed", json.loads(e.read() or b"{}").get("error", str(e))) from None
    except OSError as e:
        raise CallError("unreachable", f"board unreachable: {e}") from None


def make_device() -> tuple[Device, Any]:
    dev = Device("keyscreen-01", "display", name="KeyScreen touch keyboard", model="LubanCat 1H + touch display", state={
        "profile": {"type": "string", "writable": True, "description": "active per-app profile"},
        "wallpaper": {"type": "string", "description": "wallpaper of the active profile"},
        "miss_rate": {"type": "number", "min": 0, "max": 1, "description": "share of touches that missed every key", "alert": {"warn": 0.1, "bad": 0.2}},
    })
    touch = dev.source("touch", "values", "typing statistics from the touch surface", hz=1, default=True, fields={
        "total": {"type": "integer", "min": 0},
        "miss_rate": {"type": "number", "min": 0, "max": 1},
        "latency_ms": {"type": "number", "unit": "ms", "min": 0, "max": 1000},
    })

    async def on_set(name: str, value: Any) -> None:
        if name == "profile":
            await call("POST", f"/api/active/{value}")
            dev.update(profile=value)

    dev.on_set = on_set

    @dev.tool("List wallpapers stored on the keyboard and the active profile.", timeout=10)
    async def list_wallpapers(call_: Any) -> dict:
        s = await call("GET", "/api/state")
        return {"wallpapers": s["wallpapers"], "active": s["active"], "profile": s["profile"], "profiles": s["profiles"]}

    @dev.tool("Set the wallpaper (and optional accent theme colour #rrggbb, key opacity 0-255) of a profile.",
              params={"wallpaper": {"type": "string"}, "profile": {"type": "string"}, "theme": {"type": "string"}, "opacity": {"type": "integer", "minimum": 0, "maximum": 255}},
              required=["wallpaper"], timeout=10)
    async def set_wallpaper(call_: Any, wallpaper: str, profile: str | None = None, theme: str | None = None, opacity: int | None = None) -> dict:
        body = {"wallpaper": wallpaper, **({"theme": theme} if theme else {}), **({"opacity": opacity} if opacity is not None else {})}
        r = await call("PUT", f"/api/profile/{profile or dev.state.get('profile') or 'default'}", body)
        dev.update(wallpaper=wallpaper)
        return r["profile"]

    @dev.tool("Create or update a per-app profile: legends maps key label to shown text, modules lists bar items (clock, app, wpm).",
              params={"app": {"type": "string"}, "legends": {"type": "object"}, "modules": {"type": "array", "items": {"type": "string"}}, "activate": {"type": "boolean"}},
              required=["app"], timeout=10)
    async def set_profile(call_: Any, app: str, legends: dict | None = None, modules: list | None = None, activate: bool = False) -> dict:
        body = {k: v for k, v in {"legends": legends, "modules": modules, "activate": activate}.items() if v is not None}
        r = await call("PUT", f"/api/profile/{app}", body)
        if activate:
            dev.update(profile=app)
        return r["profile"]

    @dev.tool("Nudge one key's touch area by dx/dy pixels (each clamped to ±40) to reduce misses.",
              params={"key": {"type": "string"}, "dx": {"type": "number", "minimum": -20, "maximum": 20}, "dy": {"type": "number", "minimum": -20, "maximum": 20}},
              required=["key", "dx", "dy"], timeout=10)
    async def adjust_key(call_: Any, key: str, dx: float, dy: float) -> dict:
        return await call("POST", "/api/keys/adjust", {"key": key, "dx": dx, "dy": dy})

    @dev.tool("Per-key touch statistics: count, miss_rate, average offset from key centre (dx, dy px) and press time.",
              params={"since_minutes": {"type": "number", "minimum": 0}}, timeout=10)
    async def get_touch_stats(call_: Any, since_minutes: float = 0) -> dict:
        since = time.time() - since_minutes * 60 if since_minutes else 0
        r = await call("GET", f"/api/touch/stats?since={since}")
        r["keys"] = r["keys"][:25]
        return r

    @dev.tool("Describe the rendered keyboard (size, active profile, wallpaper) to preview a layout change.", timeout=10)
    async def preview_layout(call_: Any) -> dict:
        s = await call("GET", "/api/state")
        png = await call("GET", "/api/screenshot")
        return {"size": s["size"], "active": s["active"], "wallpaper": s["profile"]["wallpaper"], "theme": s["profile"]["theme"], "screenshot_bytes": len(png), "screenshot_url": BOARD + "/api/screenshot"}

    async def poll() -> None:
        while True:
            try:
                s = await call("GET", "/api/state")
                st = await call("GET", "/api/touch/stats")
                dev.problem = None
                dev.update(profile=s["active"], wallpaper=s["profile"]["wallpaper"] or "", miss_rate=st["miss_rate"])
                if touch.wants():
                    touch.send({"total": st["total"], "miss_rate": st["miss_rate"], "latency_ms": s["latency_ms"] or 0})
            except Exception as e:
                dev.problem = f"board unreachable: {e}"
            await asyncio.sleep(1)

    return dev, poll


async def main(url: str) -> None:
    dev, poll = make_device()
    task = asyncio.ensure_future(poll())
    try:
        await dev.run(url)
    finally:
        task.cancel()


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--board" in args:
        i = args.index("--board")
        BOARD = args[i + 1]
        del args[i:i + 2]
    asyncio.run(main(args[0] if args else "ws://127.0.0.1:8800"))
