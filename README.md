# KeyScreen：鲁班猫 1H 触控动态键盘（Flux Keyboard 风格）

The touch display renders the key positions, wallpaper, and module bar. Touches are mapped to keys and sent to the computer as a USB HID keyboard. The computer side uploads wallpapers, edits per-app profiles, and shows a heatmap. The Agnes model (`agnes-3.0-flash`) controls the keyboard through AGH + MHS.

```
board/keyscreen.py   板端：pygame 渲染 + evdev 触摸 + /dev/hidg0 HID + SQLite 日志 + API :8765
board/hid_gadget.sh  configfs 把 OTG 口配置成 USB 键盘
board/bringup.sh     板子一键自检 + 装 systemd 服务
board/mhs_device.py  把键盘登记为 MHS 设备 keyscreen-01（6 个工具 + touch 数据源）
desktop/panel.py     电脑端控制台 :43125 + 前台应用自动切 profile
.agh/skills/         wallpaper-advisor、layout-tuner 两个 Agnes Skill
sim.sh               无硬件演示
```

## 无硬件演示

```bash
pip3 install --user pygame aiohttp pillow
./sim.sh            # 弹出键盘窗口（鼠标=手指），加 --headless 则无窗口
```
Open the panel at http://127.0.0.1:43125 and the dev hub at http://127.0.0.1:4191 (it shows keyscreen-01).

## 上板（鲁班猫 1H）

1. Flash the official Ubuntu 22.04 image. Connect the display's HDMI to the board's HDMI and the display's touch USB to the board's USB-A port. Connect the board's **OTG Type-C** port to the computer. Power the board from 12V DC.
2. If the OTG port defaults to host mode, use the official `/boot/uEnv` overlay or device tree to set it to `dr_mode=peripheral`.
3. Copy `board/` to the board and run `sudo sh bringup.sh`. Every item should show `[PASS]`: HDMI, touch, `/dev/hidg0`, and systemd.
4. `sudo systemctl start keyscreen`. On the computer, run `python3 desktop/panel.py --board http://<板子IP>:8765`.
   - Also works with the vendor **Debian 10** image (tested: kernel 4.19.232, LubanCat 1H). That kernel already has `CONFIG_USB_CONFIGFS_F_HID=y`, so no `dr_mode` change is needed. `hid_gadget.sh` adds HID to the vendor `rockchip` gadget, `bringup.sh` installs pygame and aiohttp offline from `board/wheels`, then runs the UI under the existing X session and disables leftover `fluxboard-*` services.
   - Direct cable without DHCP: the computer's NIC is on 169.254.x. Give the board an address in the same /24 (e.g. `nmcli con mod <conn> +ipv4.addresses 169.254.220.2/16`) so `deploy.sh` can find it. Under WSL, use `KS_PASS=temppwd ./deploy.sh` to avoid an interactive sudo prompt.
5. Troubleshooting: run `evtest` to inspect raw touch events. On the computer, the new device "KeyScreen Touch Keyboard" should appear.

## 接入 Agnes（比赛要求的运行时）

```bash
cd agnes-harness && node packages/cli/dist/local/agnes.mjs daemon stop   # 守护进程须从 agnes-harness 根目录启动，否则 file:./ 源被拒
pnpm --filter @agnes/mhs plugin:install                          # 在真终端里输入 y
node packages/cli/dist/local/agnes.mjs package trust @agnes/mhs <integrity> <capabilityHash>
node packages/cli/dist/local/agnes.mjs package enable @agnes/mhs # 之后 4180 端口即 AgnesHub
AGNES_HUB_ORIGIN=http://127.0.0.1:4180 ../scripts/serve.sh
HUB=ws://127.0.0.1:4180 ./sim.sh                                 # 或板子上把 mhs_device.py 指向电脑的 4180
```
Start AGH from this directory (`work/keyscreen`). It loads the two skills automatically. Example prompts:
- "I'm writing code now. Pick a wallpaper that suits it from the keyboard and adjust the theme colour."
- "Look at my typing stats from the last 30 minutes, fix keys I often miss, and set VS Code shortcut legends for me."

## 验证结果（模拟环境，见 evidence/）

| 项 | 结果 |
|---|---|
| Touch → key → HID report latency | 0.025 ms (target < 30 ms) |
| Wallpaper upload / profile switch / screenshot / stats API | Passed |
| HID report | Tapping E produces `0000080000000000` then `0000000000000000` |
| mhs-check (core, perception, streaming) | **38 pass, 0 fail**, 13 skip (motion/video items, not applicable) |
| Bad wallpaper, board unreachable, unknown key | No crash; returns an error or MHS `problem` |

Demo video script: run `sim.sh` → upload a wallpaper in the panel → click keys with the mouse so the heatmap updates → in AGH, ask Agnes to recommend a wallpaper and tune keys → the keyboard view changes.
