# KeyScreen：让 Agnes 用真实触摸数据闭环优化一块触控键盘

**问题**：平面触控键盘（手机、平板、Flux Keyboard 这类屏幕键盘）没有键帽回弹，用户的落点会系统性偏离按键中心，误触率随使用习惯、应用场景和壁纸对比度变化。传统做法是出厂固定布局 + 人工在设置里微调。

**我们的做法**：把一块 LubanCat 1H + 便携触摸屏做成真正的 USB HID 键盘（电脑把它识别成普通键盘），板端记录每一次触摸的落点、命中键、相对键心偏移和按压时长；再把键盘登记为 Agnes 的 **MHS 设备 `keyscreen-01`**，让 `agnes-3.0-flash` 通过 Agnes Harness（AGH）读取这些统计，**自行决定**把哪些键的触控区域朝用户习惯的方向挪、换什么壁纸/主题色/不透明度来保证图例可读。模型给出的每个动作都经 MHS 工具落到真机，变化立即在屏幕和 HID 行为上体现。

```
board/keyscreen.py   板端：pygame 渲染 + evdev 多点触摸 + /dev/hidg0 6KRO HID + SQLite 触摸日志 + HTTP/WS API :8765 + /ui/ 客户端
board/hid_gadget.sh  configfs 在厂商 rockchip gadget 上追加 HID 功能（Windows 识别为 "KeyScreen Touch Keyboard"）
board/bringup.sh     板子一键自检（HDMI/触摸/HID/服务）+ 装 systemd 服务，离线安装 wheels
board/mhs_device.py  把键盘登记为 MHS 设备 keyscreen-01：6 个工具 + touch 数据源 + 状态/告警
desktop/web/         浏览器客户端：壁纸（含 GIF/WebP/MP4 动态）、按键特效、profile、热力图
.agh/skills/         wallpaper-advisor、layout-tuner 两个 Agnes Skill（模型的操作规程）
evidence/            真机验证证据（见下）
sim.sh               无硬件演示
```

## Agnes 闭环（真机已跑通，证据在 `evidence/agnes-loop/`）

数据流：触摸屏 → `keyscreen.py`（命中判定、HID 报告、落点日志）→ `/api/touch/stats` → `mhs_device.py`（MHS 设备）→ AgnesHub :4180 → AGH 工具 `read_device / call_device` → **agnes-3.0-flash** 决策 → `call_device adjust_key / set_wallpaper` → 板端改 profile → 下一次触摸按新区域判定。

| 运行 | 提示词（节选） | 模型做了什么 | 真机结果 |
|---|---|---|---|
| run2 `layout-tuner` | 看全部触摸统计，挑偏移最大的 2 个键按一半偏移量微调 | 调 `get_touch_stats` → 从 25 个键里按 \|dx\|+\|dy\| 选出 S（42 px）和 Shift（68 px）→ 两次 `adjust_key` | `profile.offsets = {S: [-8,-13], Shift: [-14, 20]}`，截图 `after2.jpg` 中 S/Shift 图例已移位 |
| run3 `wallpaper-advisor` | 写代码场景，从板上壁纸中选一张并配色 | `list_wallpapers` 看到 3 张 → 选 `dark_ocean.png`，主题 `#5D7B8A`，不透明度 110，给出备选 `neon_tiles` + `#3EB489` | `state_after3.json`、`after3.jpg` |
| run1（修复前） | 同 run3，当时板上只有 1 张壁纸 | 只改了主题色 `#38bdf8 → #4C6FFF` | `state_after1.json` |

两点在真实闭环里才暴露、并已修复的问题（记录在 `run2_layout.txt` 首次失败版本的描述里）：
1. **MHS 工具返回值协议**：Python 设备库只把 `detail/data/notes` 三个键回传，模型只能看到 `detail` 文本。最初工具直接返回原始 dict，模型看到的只是 "get_touch_stats done"，于是回答"没有按键级数据"。修复：每个工具用 `reply(detail, data)` 把统计压成一行文本给模型、完整 JSON 留给设备面板。
2. **模型越界**：Shift 的 dy 应 ≤15，模型给了 20。板端 `adjust_key` 把每个键的累计偏移钳在 ±40 px（键高 108 px 的 37%），所以越界不会把键挪出可点区域——这是 MHS 设备侧必须有的防御。

## 真机验证（LubanCat 1H，Debian 10，内核 4.19.232；证据在 `evidence/board/`）

| 项 | 结果 |
|---|---|
| USB HID | Windows 设备管理器：`KeyScreen Touch Keyboard` VID 2207 PID 0019；记事本实际打出字母 |
| 触摸→HID 报告延迟 | 40 次注入：平均 **1.75 ms**，p95 **3.3 ms**（薄膜键盘扫描周期约 8 ms）；播放 15 fps 视频壁纸时 p95 1.6 ms |
| 稳定性 | 100 次快速连击后 `NRestarts=0`；上电自启 `ActiveState=active`（`service_status.txt`） |
| 异常处理 | 坏壁纸/板子不可达/未知键：API 返回错误或 MHS `problem`，进程不退出；渲染循环 try/except 包裹，特效 alpha 钳位修复了曾经的 `invalid color argument` 崩溃 |
| 真实触摸统计 | 362 次真实触摸，整体 miss 1.9%，Bksp miss 9.1%、avg_dy −16 px；S avg_dx −17/dy −25 px（`touch_stats.json`）|
| mhs-check | 38 pass / 0 fail / 13 skip（`mhs-check.txt`，skip 为摄像头/运动类不适用项）|

## 复现

```bash
# 1. 板子：拷 board/ 上板，sudo sh bringup.sh（全部 [PASS]），systemctl start keyscreen；客户端 http://<板子IP>:8765/ui/
# 2. 电脑：仓库根目录 scripts/bootstrap.sh 构建 AGH，scripts/agh.sh config 配 Agnes AI 密钥（密钥只落在 .agh/secrets）
# 3. 装 MHS 插件（见仓库根 README「MHS」一节），AgnesHub 监听 127.0.0.1:4180
PYTHONPATH=agnes-harness/packages/mhs/python/src python3 board/mhs_device.py ws://127.0.0.1:4180 --board http://<板子IP>:8765
AGNES_HUB_ORIGIN=http://127.0.0.1:4180 scripts/agh.sh serve --home .agh --profile local-dev --cwd work/keyscreen --port 43117
# 4. 一条命令跑闭环（print 模式）
scripts/agh.sh -p "调用 keyscreen-01 的 get_touch_stats，挑偏移最大的两个键用 adjust_key 微调并汇报" --cwd work/keyscreen --mode text
```

无硬件：`./sim.sh`（鼠标当手指），其余步骤相同。

## 上板细节（LubanCat 1H）

- 厂商 Debian 10 镜像内核已带 `CONFIG_USB_CONFIGFS_F_HID=y`，无需改 `dr_mode`。`hid_gadget.sh` 不新建 gadget（第二个 gadget 会触发内核 oops），而是在现有 `rockchip` gadget 上加 `hid.usb0`，所有属性写完再绑定 UDC，避开 `usb-hotplug` 的自动重绑。报告描述符用 `bytes.fromhex` 写入（dash 的 printf 会把 `\x` 写成字面量，Windows 报错代码 10）。
- `bringup.sh` 停用遗留的 `fluxboard-*` 服务（占用 8765 端口），从 `board/wheels` 离线装 pygame/aiohttp，服务挂在现有 lightdm X 会话下。
- 直连网线无 DHCP：给板子加 `169.254.x.x` 地址（`nmcli con mod <conn> +ipv4.addresses 169.254.220.2/16`）。WSL 下 `KS_PASS=temppwd ./deploy.sh`。
- 排查：`evtest` 看原始触摸；`journalctl -u keyscreen`。
