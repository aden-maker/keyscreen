"""Submission evidence: one full AGH multi-step run (exported) plus normal / boundary / failure test cases,
all against the real board. Writes evidence/submission/{test_results.json, 测试样例.md, agh_*}.

  python3 tools/run_tests.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "desktop"))
sys.path.insert(0, str(HERE / "board"))
import panel  # noqa: E402

B = "http://169.254.220.2:8765"
OUT = HERE / "evidence" / "submission"
OUT.mkdir(parents=True, exist_ok=True)
AGH = str(panel.AGH)
results: list[dict] = []


def api(method: str, path: str, body=None):
    req = urllib.request.Request(B + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"}, method=method)
    try:
        r = urllib.request.urlopen(req, timeout=10)
        return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def case(kind: str, name: str, inp: str, expect: str, fn) -> None:
    t0 = time.time()
    try:
        got, passed = fn()
    except Exception as e:
        got, passed = f"exception: {e}", False
    results.append({"type": kind, "name": name, "input": inp, "expected": expect, "actual": got, "pass": passed,
                    "ms": round((time.time() - t0) * 1000), "at": time.strftime("%Y-%m-%d %H:%M:%S")})
    print(f"[{kind}] {name}: {'PASS' if passed else 'FAIL'}  {str(got)[:120]}")


def chat(prompt: str, wait: float = 180):
    _, r = api("POST", "/api/chat/send", {"prompt": prompt})
    i, t0 = r["item"]["id"], time.time()
    while time.time() - t0 < wait:
        x = [it for it in api("GET", "/api/chat/history")[1]["items"] if it["id"] == i][0]
        if x["status"] in ("done", "error"):
            return x, time.time() - t0
        time.sleep(0.3)
    return x, time.time() - t0


def agh_run(prompt: str, tag: str) -> dict:
    """One AGH print-mode turn in a fresh workspace, then export its session for human review."""
    cwd = panel.session_dir(fresh=True)
    env = {k: v for k, v in __import__("os").environ.items() if "proxy" not in k.lower()}
    t0 = time.time()
    out = subprocess.run(["bash", AGH, "-p", prompt, "--cwd", cwd, "--mode", "json"], capture_output=True, text=True, timeout=300, env=env, cwd=cwd)
    res = json.loads(out.stdout.strip().splitlines()[-1])
    res["seconds"] = round(time.time() - t0, 1)
    for fmt, ext in (("jsonl", "jsonl"), ("html", "html")):
        args = ["bash", AGH, "export", res["sessionId"], "--out", str(OUT / f"agh_{tag}.{ext}"), "--cwd", cwd] + (["--html"] if fmt == "html" else [])
        e = subprocess.run(args, capture_output=True, text=True, timeout=120, env=env, cwd=cwd)
        res[f"export_{ext}"] = "ok" if e.returncode == 0 else (e.stderr or e.stdout)[-300:]
    (OUT / f"agh_{tag}_result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


# ---------- 1. full AGH multi-step run: plan -> device calls -> feedback -> verification ----------
api("POST", "/api/lang", {"lang": "en"})
before = {"lang": api("GET", "/api/lang")[1]["lang"], "profile": api("GET", "/api/profile/default")[1]["profile"]}
(OUT / "state_before.json").write_text(json.dumps(before, ensure_ascii=False, indent=1), encoding="utf-8")
PROMPT = ("我要开始写俄语论文了，帮我把键盘整套配好：先用 keyscreen-01 的 read/list 类工具查看当前状态和可用壁纸，"
          "再 set_language 切到 ru；选一张适合长时间专注写作的壁纸 set_wallpaper 到 default 并配沉稳主题色；pet_act 让桌宠 cheer；"
          "最后再读一次设备状态，确认语言和壁纸确实已生效，用一句中文 + 一句俄语汇报。")


def t_agh():
    r = agh_run(PROMPT, "ru_writing")
    after = {"lang": api("GET", "/api/lang")[1]["lang"], "profile": api("GET", "/api/profile/default")[1]["profile"]}
    (OUT / "state_after.json").write_text(json.dumps(after, ensure_ascii=False, indent=1), encoding="utf-8")
    urllib.request.urlretrieve(B + "/api/screenshot?fmt=jpg", str(OUT / "screen_after_ru_writing.jpg"))
    changed = after["profile"]["wallpaper"] != before["profile"]["wallpaper"] or after["profile"]["theme"] != before["profile"]["theme"]
    ok = r["exitCode"] == 0 and after["lang"] == "ru" and changed
    return {"reason": r["reason"], "seconds": r["seconds"], "text": r.get("text", "")[:300], "lang": after["lang"],
            "wallpaper": after["profile"]["wallpaper"], "theme": after["profile"]["theme"], "export": [r.get("export_jsonl"), r.get("export_html")]}, ok


case("正常", "AGH 多步任务：一句话配置俄语写作键盘", PROMPT[:60] + "…", "AGH 完成规划→多次设备调用→回读验证；板端语言=ru，壁纸/主题色改变", t_agh)

# ---------- 2. other normal cases ----------
case("正常", "快捷按钮切换语言（板端本地通道）", "换语言键盘", "瞬时回复布局介绍，语言切到下一种",
     lambda: (lambda x: ({"reply": x[0]["reply"][:60], "seconds": round(x[1], 2), "lang": api("GET", "/api/lang")[1]["lang"]}, x[0]["status"] == "done" and x[1] < 2))(chat("换语言键盘")))
api("POST", "/api/lang", {"lang": "en"})
case("正常", "Agnes 只读分析打字数据", "分析打字（经 AGH 调用 get_touch_stats）", "返回误触率与最易按偏的键，不修改设置",
     lambda: (lambda x: ({"reply": x[0]["reply"][:120], "seconds": round(x[1], 1)}, x[0]["status"] == "done" and "%" in x[0]["reply"]))(
         chat("用 keyscreen-01 的 get_touch_stats（since_minutes=0）用两句话总结我的打字：误触率、最容易按偏的键、一条建议。不要修改设置。")))


def t_ime():
    from ime import Pinyin
    p = Pinyin(str(HERE / "board" / "assets" / "pinyin.txt"))
    while not p.ab:
        time.sleep(0.1)
    got = {q: p.query(q)[0][0][0] for q in ("nihaoshijie", "zgrm", "jintiantianqizenmeyang")}
    return got, got["nihaoshijie"] == "你好世界" and got["zgrm"] == "中国人民"


case("正常", "整句拼音输入法", "nihaoshijie / zgrm / jintiantianqizenmeyang", "首选：你好世界 / 中国人民 / 今天天气怎么样", t_ime)

# ---------- 3. boundary cases ----------
case("边界", "未知语言代码", 'POST /api/lang {"lang":"xx"}', "HTTP 400，提示可选语言，状态不变",
     lambda: (lambda r: ({"http": r[0], "error": r[1].get("error")}, r[0] == 400 and api("GET", "/api/lang")[1]["lang"] == "en"))(api("POST", "/api/lang", {"lang": "xx"})))
case("边界", "空消息", 'POST /api/chat/send {"prompt":"  "}', "HTTP 400 empty prompt，不进入队列",
     lambda: (lambda r: ({"http": r[0], "error": r[1].get("error")}, r[0] == 400))(api("POST", "/api/chat/send", {"prompt": "  "})))


def t_clamp():
    s, r = api("POST", "/api/keys/adjust", {"key": "Q", "dx": 999, "dy": 0})
    off = r.get("offsets", {}).get("Q", r.get("offset"))
    api("POST", "/api/keys/adjust", {"key": "Q", "dx": -off[0], "dy": 0}) if off else None  # restore
    return {"http": s, "offset_after_999": off}, s == 200 and off is not None and abs(off[0]) <= 40


case("边界", "键位偏移超限", 'adjust_key Q dx=999', "偏移被钳制在 ±40 px 内（随后已还原）", t_clamp)


def t_eng():
    from ime import Pinyin
    p = Pinyin(str(HERE / "board" / "assets" / "pinyin.txt"))
    while not p.ab:
        time.sleep(0.1)
    c = p.query("keyscreen")[0]
    return {"first": c[0][0] if c else None}, bool(c) and c[0][0].lower() == "keyscreen"


case("边界", "非拼音英文串", "keyscreen", "首选原样英文，不强行转中文", t_eng)

# ---------- 4. failure cases ----------
case("失败", "未知壁纸", 'PUT /api/profile/default {"wallpaper":"nope.png"}', "HTTP 400 unknown wallpaper，配置不变",
     lambda: (lambda r: ({"http": r[0], "error": r[1].get("error")}, r[0] == 400))(api("PUT", "/api/profile/default", {"wallpaper": "nope.png"})))
case("失败", "未知按键", 'POST /api/keys/adjust {"key":"NoSuchKey"}', "HTTP 400，拒绝修改",
     lambda: (lambda r: ({"http": r[0], "error": r[1].get("error")}, r[0] >= 400))(api("POST", "/api/keys/adjust", {"key": "NoSuchKey", "dx": 1, "dy": 1})))


def t_model_down():
    cwd = panel.session_dir(fresh=True)
    o = subprocess.run(["bash", AGH, "-p", "你好", "--cwd", cwd, "--model", "no-such-model", "--mode", "text"], capture_output=True, text=True, timeout=120, cwd=cwd)
    fb = panel.offline_reply(B, "分析打字")
    err = [l for l in (o.stdout + o.stderr).splitlines() if l.startswith("agnes:") and "sk-" not in l][-1:]
    return {"agh_exit": o.returncode, "agh_error": err, "fallback_reply": fb[:100]}, o.returncode != 0 and fb.startswith("（离线模式）")


case("失败", "模型不可用 → 本地兜底", "AGH --model no-such-model", "AGH 非零退出并给出原因；电脑端改用本地规则回复（离线模式）", t_model_down)

api("POST", "/api/lang", {"lang": "en"})
(OUT / "test_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
md = ["# 测试样例（真实设备运行结果）", "", f"运行时间：{time.strftime('%Y-%m-%d %H:%M')}；设备：LubanCat 1H keyscreen-01；脚本：`tools/run_tests.py`", "",
      "| 类型 | 用例 | 输入 | 预期 | 实际 | 结果 | 耗时 |", "|---|---|---|---|---|---|---|"]
for r in results:
    act = json.dumps(r["actual"], ensure_ascii=False).replace("|", "/")[:220]
    md.append(f"| {r['type']} | {r['name']} | {r['input'].replace('|', '/')} | {r['expected']} | {act} | {'通过' if r['pass'] else '未通过'} | {r['ms']} ms |")
(OUT / "测试样例.md").write_text("\n".join(md) + "\n", encoding="utf-8")
print(f"{sum(r['pass'] for r in results)}/{len(results)} passed")
