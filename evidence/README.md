# 证据索引

所有文件来自真机（LubanCat 1H @169.254.220.2）与本机 AGH（agnes-3.0-flash）在 2026-10-13 的实际运行，未经人工编辑。

## agnes-loop/ — Agnes 通过 AGH + MHS 控制真机
- `run1_wallpaper.txt` / `state_before.json` → `state_after1.json`：首次闭环，模型把主题色 `#38bdf8` 改为 `#4C6FFF`（当时板上只有 1 张壁纸）。
- `run2_layout.txt` / `state_after2.json` / `after2.jpg`：layout-tuner。模型读 `get_touch_stats`，选 S、Shift 两键，`adjust_key` 后 `profile.offsets = {S:[-8,-13], Shift:[-14,20]}`。
- `run3_wallpaper.txt` / `state_after3.json` / `after3.jpg`：wallpaper-advisor。3 张候选中选 `dark_ocean.png`，主题 `#5D7B8A`，不透明度 110。
- `touch_stats_before.json`：模型决策所依据的原始按键统计。
- `before.jpg`：闭环前的板端截图。
- `package_status.txt`：`@agnes/mhs` desired=enabled actual=running trusted=true。
- `doctor_provider.json`：AGH provider 路由已配置（密钥不在输出中）。

## board/ — 板端指标
- `latency.json`：40 次触摸注入后的触摸→HID 延迟 avg 1.75 ms / p95 3.3 ms。
- `service_status.txt`：上电 2 分钟 `ActiveState=active NRestarts=0`，`/dev/hidg0` 存在，UDC `fcc00000.dwc3`，启动日志。
- `touch_stats.json`：362 次真实触摸的逐键统计（count / miss_rate / avg_dx / avg_dy / avg_ms）。
- `state_summary.json`、`hid_last.json`：API 状态快照。

## mhs-check.txt
`agnes_mhs` 一致性检查：38 pass / 0 fail / 13 skip。
