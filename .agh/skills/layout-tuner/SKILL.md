---
name: layout-tuner
description: Analyse KeyScreen touch statistics (misses, offset from key centres) and tune key hit areas, per-app legends and the module bar through the keyscreen-01 MHS device.
---

# Layout tuner

1. `call_device keyscreen-01 get_touch_stats {since_minutes: 30}` (use 0 for all time).
2. For each key with `count >= 8`:
   - If `|avg_dx| > 12` or `|avg_dy| > 12` px, the user consistently presses off-centre. Call `adjust_key {key, dx: round(avg_dx/2), dy: round(avg_dy/2)}`. Move it by half the offset per step and never by more than 20 px.
   - If `miss_rate > 0.15`, mention the key and its neighbours.
3. Per-app shortcuts: when the user names an app, call `set_profile {app, legends, modules, activate}`. Legends map key labels to short text (at most 6 characters), for example VS Code `{"P":"命令","F":"查找","S":"保存"}`. Modules come from `clock`, `app`, `wpm`.
4. Read the stats again after the user types more. Report the overall miss_rate before and after, in one short table.

Only change keys that the data supports; say so when there are not enough touches.
