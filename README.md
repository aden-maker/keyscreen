# KeyScreen

[English](README.md) | [简体中文](README_zh.md)

An Agnes-driven multi-language touch keyboard: a LubanCat 1H + capacitive touchscreen becomes a plug-and-play USB HID keyboard that `agnes-3.0-flash` can read and reconfigure through Agnes Harness (AGH) and an MHS device.

> Hackathon entry for **2026 Jiangsu AI + Science & Engineering Innovation Practice Hackathon** (undergraduate track, team U376 · 无敌键队).  
> Public demo: [Bilibili BV14hpS6yEPk](https://www.bilibili.com/video/BV14hpS6yEPk/) · Source: [github.com/aden-maker/keyscreen](https://github.com/aden-maker/keyscreen)

---

## Intro

**Problem.** Flat touch keyboards have no keycap feedback. Finger landings systematically drift off key centers; miss rate changes with habit, posture, wallpaper contrast, and language. Buying a Russian/French/German keyboard or sticking keycaps does not keep legends in sync with the host OS layout. Large models chat well but rarely operate nearby hardware safely.

**What we built.** KeyScreen turns a LubanCat 1H development board and a portable touchscreen into a real USB HID keyboard (Windows/macOS/Linux, no driver). Everything on the screen is soft: key regions, legends, language layouts (EN / RU / FR / DE), wallpaper, theme, key effects, and a desk pet. Those capabilities are exposed as an MHS device `keyscreen-01`. Through AGH, `agnes-3.0-flash` can:

- read per-key touch statistics and nudge key hit-boxes toward the user’s habit;
- switch language layout and sync the Windows keyboard layout in ~1 s;
- pick wallpapers / theme colors / opacity for coding or writing scenes;
- drive the desk pet (wave, dance, cheer) as visible feedback;
- run multi-step plans from one natural-language goal (e.g. “I need to write a Russian paper—set the keyboard up”).

On a real device that prompt took ~17 s and 6 tool calls; every step is exportable via `agh export` for audit.

**Core idea.**

```text
Agent product = Model (agnes-3.0-flash) + Harness (AGH) + Device (MHS keyscreen-01)

The model plans and decides.
The harness routes tools and keeps an execution log.
The device validates, clamps, and applies changes on real hardware.
```

---

## Demo Video

| | |
|---|---|
| **Bilibili (no login required)** | https://www.bilibili.com/video/BV14hpS6yEPk/ |
| Duration | ~5 min · 1080p |
| Contents | Hardware bring-up · USB typing · Agnes multi-step Russian-writing setup · client panel modules · language cycle · calibration experiment · reliability tests |

Offline copy used in the submission package: `KeyScreen_演示视频.mp4`.

---

## Architecture

Two paths run side by side.

### Typing path (low latency)

```text
Touchscreen (evdev multi-touch)
        │
        ▼
LubanCat 1H  ·  keyscreen.py
  · hit test (1920×1080 key rects)
  · sentence Pinyin IME (47k lexicon, Viterbi, <1 ms/key)
  · pygame dirty-rect render · pet / weather / wallpaper
        │
        ▼
USB HID gadget (/dev/hidg0, 6KRO boot report)
        │
        ▼
Host PC  (standard keyboard, no driver)
```

Measured on board: touch → HID send avg **1.75 ms** (p95 ~3.3 ms); key → screen update median ~34 ms; screen refresh 48 ms → **27 ms** after disabling the xfwm4 compositor.

### Intelligence path (Agnes operates the keyboard)

```text
User utterance (panel / on-device chat / AGH CLI)
        │
        ▼
AGH  ·  agnes-3.0-flash
        │  tool_use
        ▼
MHS device keyscreen-01  (board/mhs_device.py)
        │  REST
        ▼
Board API :8765  →  profile / lang / wallpaper / offsets / pet
        │
        ▼
Next touch uses the new regions; screen updates immediately
```

```text
Repository layout
.
├── board/                 # On-device runtime
│   ├── keyscreen.py       # Render + touch + HID + REST/WS API
│   ├── mhs_device.py      # MHS device keyscreen-01 + tools
│   ├── ime.py             # Sentence Pinyin IME
│   ├── hid_gadget.sh      # configfs HID on rockchip gadget
│   ├── bringup.sh         # One-shot board setup + systemd
│   └── pet.py / weather.py / widgets.py
├── desktop/
│   ├── panel.py           # PC panel: Agnes bridge, layout follow, weather
│   ├── web/               # Browser client UI
│   └── 提交说明/          # Submission docs (Chinese)
├── .agh/skills/           # layout-tuner · wallpaper-advisor
├── evidence/              # Real-device runs, AGH exports, tests
├── tools/                 # run_tests.py, deck builders, …
├── demo.sh                # One-click PC-side demo
└── sim.sh                 # No-hardware simulation (mouse as finger)
```

---

## Integration Standards

### 1. Must use Agnes Harness + Agnes models only

Per hackathon rules: all agent execution goes through **AGH**; all model calls use **Agnes models only** (we use `agnes-3.0-flash`). No third-party LLM APIs.

### 2. MHS device contract (`keyscreen-01`)

The board is registered as an MHS **display** device. Tools the model may call:

| Tool | Effect |
|---|---|
| `list_wallpapers` | List wallpapers on the board |
| `set_wallpaper` | Set wallpaper / theme `#rrggbb` / key opacity |
| `set_profile` | Create/update per-app profile (legends, modules) |
| `set_language` | Switch `en` / `ru` / `fr` / `de` |
| `adjust_key` | Nudge one key’s hit-box by `dx,dy` (clamped ±40 px) |
| `get_touch_stats` | Per-key count, miss rate, mean offset, hold time |
| `preview_layout` | Describe current rendered layout |
| `pet_say` / `pet_act` | Desk-pet speech bubble / jump·wave·dance·cheer |

Safety on the device side (not only in the prompt):

- unknown language / wallpaper / key → HTTP 400;
- cumulative key offset clamped to **±40 px**;
- tool results use `reply(detail, data)` so the model sees a readable `detail` line while the Devices page keeps full JSON;
- every AGH run is exportable: `agh export <sid> --out … [--html]` (auto-redacted).

### 3. Board REST surface (for panel & tests)

Base URL `http://<board-ip>:8765`, for example:

- `GET /api/state` · `GET /api/screenshot`
- `POST /api/lang` · `PUT /api/profile/default`
- `POST /api/touch/inject` · `GET /api/stats` / heatmaps
- `POST /api/chat/send` · `POST /api/chat/open`
- `POST /api/pet/act` · wallpaper upload endpoints

### 4. Skills (operation playbooks)

- `.agh/skills/layout-tuner` — read stats → pick worst keys → half-offset `adjust_key`
- `.agh/skills/wallpaper-advisor` — pick wallpaper + theme for a scene (coding / anime / focus)

### 5. Secrets

API keys live only under local `.agh/secrets/` with mode `600`. **Never** commit keys. Rotate after public demos.

---

## Reproduce

### Hardware

LubanCat 1H (Debian 10 stock image) + touchscreen. USB-C OTG → PC (keyboard). Ethernet direct or same LAN. Windows 10/11 host with WSL Ubuntu for AGH / MHS / panel.

### 1. Board (once)

```bash
scp -r board cat@<board-ip>:/home/cat/keyscreen/
ssh cat@<board-ip>
sudo sh /home/cat/keyscreen/board/bringup.sh   # offline wheels, HID, systemd
sudo systemctl start keyscreen
curl http://<board-ip>:8765/api/state          # expect JSON
```

Cold boot ~35 s → PC sees a USB keyboard and typing works.

### 2. PC (WSL)

```bash
# Install AGH per Agnes docs; put the key in .agh/secrets/ (chmod 600)
pip3 install aiohttp
BOARD=http://<board-ip>:8765 bash demo.sh
# Panel  http://127.0.0.1:43125/
# Hub    http://127.0.0.1:4180/   (device keyscreen-01)
```

### 3. Verify

```bash
# Multi-step Agnes plan
agh -p "我要开始写俄语论文了，帮我把键盘配置好" --cwd . --mode json

# Full device tests (11 cases: normal / boundary / failure)
python3 tools/run_tests.py
# → evidence/submission/ (test table, AGH html/jsonl, before/after state, screenshot)

# No hardware
./sim.sh
```

### Evidence already in-repo

| Path | Content |
|---|---|
| `evidence/agnes-loop/` | layout-tuner / wallpaper-advisor closed-loop runs |
| `evidence/board/` | HID latency, service status, touch stats, mhs-check |
| `evidence/submission/` | 11/11 tests, AGH export for Russian-writing task |

---

## License

MIT — team 无敌键队 · U376 · captain 贾灵鑫.  
Built for the 2026 Jiangsu AI + Science & Engineering Innovation Practice Hackathon.
