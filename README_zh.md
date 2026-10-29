# KeyScreen

[English](README.md) | [简体中文](README_zh.md)

一块会被 Agnes 改造的多语言触屏键盘：国产 LubanCat 1H + 电容触摸屏化身即插即用的 USB HID 键盘，`agnes-3.0-flash` 通过 Agnes Harness（AGH）与 MHS 设备直接读写硬件。

> 参赛作品：**2026 江苏省 AI+科学与工程创新实践黑客松**（本科生组 · 队伍 U376 · 无敌键队）  
> 演示视频：[B站 BV14hpS6yEPk](https://www.bilibili.com/video/BV14hpS6yEPk/) · 源码：[github.com/aden-maker/keyscreen](https://github.com/aden-maker/keyscreen)

---

## Intro（项目简介）

**问题。** 平面触屏键盘没有键帽回弹，手指落点会系统性偏离键心；误触率随习惯、坐姿、壁纸对比度和语言变化。买俄语/法语/德语键盘或贴键帽，也解决不了「键帽文字」和「电脑输入法布局」对不上的问题。大模型很会聊天，却很少能安全地动手操作身边的硬件。

**我们做了什么。** KeyScreen 把一块 LubanCat 1H 开发板和一块便携触摸屏做成真正的 USB HID 键盘（Windows / macOS / Linux 免驱）。屏幕上一切都是「软」的：键区、键帽文字、语言布局（英/俄/法/德）、壁纸、主题色、按键特效、桌宠。这些能力被封装成 MHS 设备 `keyscreen-01`。通过 AGH，`agnes-3.0-flash` 可以：

- 读取逐键触点统计，小步平移键区，贴合用户习惯；
- 切换语言布局，并在约 1 秒内同步 Windows 键盘布局；
- 为写代码 / 写作等场景挑选壁纸、主题色与不透明度；
- 指挥桌宠挥手、跳舞、欢呼，作为 AI 操作结果的可见反馈；
- 根据一句自然语言目标自主多步规划（例如「我要写俄语论文了，帮我把键盘配好」）。

在真机上，上述提示约 **17 秒、6 次工具调用**；每一步都可用 `agh export` 导出，供评委逐条核验。

**核心主张。**

```text
Agent 产品 = 模型（agnes-3.0-flash）+ Harness（AGH）+ 设备（MHS keyscreen-01）

模型负责规划与决策；
Harness 负责工具路由与执行日志；
设备侧负责校验、钳制，并把改动落到真实硬件。
```

---

## Demo Video（演示视频）

| | |
|---|---|
| **B站（无需登录）** | https://www.bilibili.com/video/BV14hpS6yEPk/ |
| 时长 | 约 5 分钟 · 1080p |
| 内容 | 硬件上电 · USB 打字 · Agnes 多步俄语写作配置 · 客户端七大模块 · 语言切换 · 校准实验 · 可靠性测试 |

提交包中的离线副本：`KeyScreen_演示视频.mp4`。

---

## Architecture（系统架构）

系统由两条并行链路组成。

### 打字链路（低延迟）

```text
触摸屏（evdev 多点触控）
        │
        ▼
LubanCat 1H  ·  keyscreen.py
  · 触点判键（1920×1080 键矩形）
  · 整句拼音输入法（4.7 万词条，Viterbi，每键 <1 ms）
  · pygame 脏矩形渲染 · 桌宠 / 天气 / 壁纸
        │
        ▼
USB HID gadget（/dev/hidg0，6 键全冲 boot 报文）
        │
        ▼
电脑主机（标准键盘，免驱）
```

板上实测：触摸 → HID 发送平均 **1.75 ms**（p95 约 3.3 ms）；按键 → 屏幕更新中位数约 34 ms；关闭 xfwm4 合成器后刷新 48 ms → **27 ms**。

### 智能链路（Agnes 动手操作键盘）

```text
用户一句话（面板 / 屏上对话 / AGH CLI）
        │
        ▼
AGH  ·  agnes-3.0-flash
        │  tool_use
        ▼
MHS 设备 keyscreen-01（board/mhs_device.py）
        │  REST
        ▼
板端 API :8765  →  profile / 语言 / 壁纸 / 键位偏移 / 桌宠
        │
        ▼
下一次触摸按新区域判定；屏幕立即更新
```

```text
仓库结构
.
├── board/                 # 板端运行时
│   ├── keyscreen.py       # 渲染 + 触摸 + HID + REST/WS API
│   ├── mhs_device.py      # MHS 设备 keyscreen-01 与工具
│   ├── ime.py             # 整句拼音输入法
│   ├── hid_gadget.sh      # 在 rockchip gadget 上追加 HID
│   ├── bringup.sh         # 一键上板 + systemd
│   └── pet.py / weather.py / widgets.py
├── desktop/
│   ├── panel.py           # 电脑端面板：Agnes 桥接、布局跟随、天气
│   ├── web/               # 浏览器客户端 UI
│   └── 提交说明/          # 参赛文档
├── .agh/skills/           # layout-tuner · wallpaper-advisor
├── evidence/              # 真机闭环、AGH 导出、测试证据
├── tools/                 # run_tests.py、答辩 PPT 生成等
├── demo.sh                # 电脑端一键演示
└── sim.sh                 # 无硬件模拟（鼠标当手指）
```

---

## Integration Standards（集成规范）

### 1. 必须使用 Agnes Harness，且仅限 Agnes 模型

按赛事要求：智能体执行底座为 **AGH**；模型调用仅限 **Agnes 模型**（本项目使用 `agnes-3.0-flash`），不得接入其他厂商大模型。

### 2. MHS 设备约定（`keyscreen-01`）

键盘登记为 MHS **display** 类设备。模型可调用的工具：

| 工具 | 作用 |
|---|---|
| `list_wallpapers` | 列出板上壁纸 |
| `set_wallpaper` | 设置壁纸 / 主题色 `#rrggbb` / 键不透明度 |
| `set_profile` | 创建或更新按应用 Profile（键帽文字、顶栏组件） |
| `set_language` | 切换 `en` / `ru` / `fr` / `de` |
| `adjust_key` | 将某键触控区平移 `dx,dy`（累计钳制 ±40 px） |
| `get_touch_stats` | 逐键次数、误触率、平均偏移、按住时长 |
| `preview_layout` | 描述当前渲染布局 |
| `pet_say` / `pet_act` | 桌宠台词 / 跳·挥手·跳舞·欢呼 |

设备侧安全边界（写在 API 里，而不是只靠提示词）：

- 未知语言 / 壁纸 / 按键 → HTTP 400；
- 键位累计偏移钳制在 **±40 px**；
- 工具返回统一 `reply(detail, data)`：模型读可读的 `detail`，设备面板保留完整 JSON；
- 每次 AGH 运行可导出：`agh export <sid> --out … [--html]`（自动脱敏）。

### 3. 板端 REST（供面板与测试）

基址 `http://<板子IP>:8765`，例如：

- `GET /api/state` · `GET /api/screenshot`
- `POST /api/lang` · `PUT /api/profile/default`
- `POST /api/touch/inject` · 统计 / 热力图接口
- `POST /api/chat/send` · `POST /api/chat/open`
- `POST /api/pet/act` · 壁纸上传等

### 4. Skills（操作规程）

- `.agh/skills/layout-tuner` — 读统计 → 选偏差最大的键 → 半偏移量 `adjust_key`
- `.agh/skills/wallpaper-advisor` — 按场景（写代码 / 二次元 / 专注）选壁纸与主题色

### 5. 密钥

API 密钥仅存放于本机 `.agh/secrets/`，权限 `600`。**禁止**写入仓库。公开演示后请到 Agnes 控制台轮换密钥。

---

## 复现步骤

### 硬件

LubanCat 1H（Debian 10 官方镜像）+ 触摸屏。USB-C OTG 接电脑（作键盘），网口直连或同一局域网。Windows 10/11 + WSL Ubuntu（跑 AGH / MHS / 面板）。

### 1. 板端（一次性）

```bash
scp -r board cat@<板子IP>:/home/cat/keyscreen/
ssh cat@<板子IP>
sudo sh /home/cat/keyscreen/board/bringup.sh   # 离线 wheels、HID、systemd
sudo systemctl start keyscreen
curl http://<板子IP>:8765/api/state            # 应返回 JSON
```

冷启动约 35 秒后，电脑识别出 USB 键盘即可打字。

### 2. 电脑端（WSL）

```bash
# 按 Agnes 文档安装 AGH；密钥放入 .agh/secrets/（chmod 600）
pip3 install aiohttp
BOARD=http://<板子IP>:8765 bash demo.sh
# 面板  http://127.0.0.1:43125/
# Hub   http://127.0.0.1:4180/   （设备 keyscreen-01）
```

### 3. 验证

```bash
# Agnes 多步任务
agh -p "我要开始写俄语论文了，帮我把键盘配置好" --cwd . --mode json

# 真机 11 条测试（正常 / 边界 / 失败）
python3 tools/run_tests.py
# → evidence/submission/（测试样例表、AGH html/jsonl、前后状态、截图）

# 无硬件
./sim.sh
```

### 仓库内已有证据

| 路径 | 内容 |
|---|---|
| `evidence/agnes-loop/` | layout-tuner / wallpaper-advisor 真机闭环 |
| `evidence/board/` | HID 延迟、服务状态、触点统计、mhs-check |
| `evidence/submission/` | 11/11 测试、俄语写作任务的 AGH 导出 |

---

## License

MIT — 队伍 无敌键队 · U376 · 队长 贾灵鑫。  
为 2026 江苏省 AI+科学与工程创新实践黑客松而建。
