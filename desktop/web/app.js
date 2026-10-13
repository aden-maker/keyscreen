const B = window.BOARD || location.origin;
const $ = (id) => document.getElementById(id);
const FX_NAMES = { none: "无", glow: "光晕", ripple: "涟漪", burst: "粒子", image: "图片" };
let S = null, sel = null, P = null;

async function j(path, opt = {}) {
  const r = await fetch(B + path, { headers: { "Content-Type": "application/json" }, ...opt });
  const d = await r.json();
  if (!d.ok) throw new Error(d.error || r.status);
  return d;
}
const status = (t, bad) => { $("status").textContent = t; $("status").className = bad ? "err" : ""; };
const enc = encodeURIComponent;

async function refresh() {
  try {
    S = await j("/api/state");
    const lat = S.latency_ms == null ? "-" : `${S.latency_ms} ms（p95 ${S.latency_p95_ms} ms）`;
    status(`已连接 ${B} · 当前 ${S.active} · 触摸→USB 延迟 ${lat}`);
  } catch (e) { return status(`连不上键盘 ${B}：${e.message}`, true); }
  sel = sel && S.profiles.includes(sel) ? sel : S.active;
  $("prof").innerHTML = S.profiles.map((p) => `<option ${p === sel ? "selected" : ""}>${p}</option>`).join("");
  P = (await j(`/api/profile/${enc(sel)}`)).profile;
  $("theme").value = P.theme; $("op").value = P.opacity; $("legend").value = JSON.stringify(P.legends);
  gallery($("walls"), S.wallpapers, P.wallpaper, "wallpapers", "还没有壁纸，先上传一张 16:9 图片", (w) => put({ wallpaper: w }));
  gallery($("fximgs"), S.effect_images, P.effect_image, "effects", "还没有特效图片", (w) => put({ effect_image: w, effect: "image" }));
  renderFx();
  stats();
}

function thumb(kind, w) {
  const src = `${B}/api/${kind}/${enc(w)}`;
  if ((S.video_ext || []).some((e) => w.toLowerCase().endsWith(e))) return `<video src="${src}" muted loop autoplay playsinline preload="metadata"></video>`;
  return `<img loading="lazy" src="${src}">`;
}
function tag(kind, w) {
  const st = kind === "wallpapers" && S.anim ? S.anim[w] : null;
  if (!st) return "";
  if (st === "ready") return `<span class="tag">动态</span>`;
  if (st === "converting") return `<span class="tag busy">转换中…</span>`;
  return `<span class="tag bad" title="${st}">转换失败</span>`;
}

function gallery(el, items, current, kind, emptyText, pick) {
  el.innerHTML = items.length ? items.map((w) =>
    `<figure class="${w === current ? "on" : ""}" data-w="${w}">${thumb(kind, w)}${tag(kind, w)}<figcaption>${w}</figcaption><button class="del" title="删除">×</button></figure>`).join("")
    : `<div class="empty">${emptyText}</div>`;
  el.querySelectorAll("figure").forEach((f) => {
    f.onclick = () => pick(f.dataset.w);
    f.querySelector(".del").onclick = async (e) => {
      e.stopPropagation();
      if (!confirm(`删除 ${f.dataset.w}？`)) return;
      try { await j(`/api/${kind}/${enc(f.dataset.w)}`, { method: "DELETE" }); refresh(); } catch (err) { status(`删除失败：${err.message}`, true); }
    };
  });
}

function renderFx() {
  $("fx").innerHTML = S.effects.map((e) => `<button data-e="${e}" class="${e === P.effect ? "on" : ""}">${FX_NAMES[e] || e}</button>`).join("");
  $("fx").querySelectorAll("button").forEach((b) => b.onclick = () => put({ effect: b.dataset.e }, true));
  $("fxtheme").checked = !P.effect_color;
  $("fxcolor").value = P.effect_color || P.theme;
  $("fxms").value = P.effect_ms; $("fxmsv").textContent = `${P.effect_ms} ms`;
  const keyOpts = S.keys.map((k) => `<option>${k.label}</option>`).join("");
  if (!$("pvkey").options.length) { $("pvkey").innerHTML = keyOpts; $("pvkey").value = "Space"; $("kekey").innerHTML = keyOpts; }
  $("keval").innerHTML = S.effects.map((e) => `<option value="${e}">${FX_NAMES[e] || e}</option>`).join("");
  const ke = P.key_effects || {};
  $("kelist").innerHTML = Object.keys(ke).length ? Object.entries(ke).map(([k, v]) =>
    `<span class="chip">${k} → ${FX_NAMES[v] || v}<button data-k="${k}" title="移除">×</button></span>`).join("") : `<span class="mut">未设置</span>`;
  $("kelist").querySelectorAll("button").forEach((b) => b.onclick = () => { const n = { ...ke }; delete n[b.dataset.k]; put({ key_effects: n }); });
}

async function put(body, preview) {
  try {
    await j(`/api/profile/${enc(sel)}`, { method: "PUT", body: JSON.stringify(body) });
    if (preview && sel === S.active) j("/api/effects/preview", { method: "POST", body: JSON.stringify({ key: $("pvkey").value }) }).catch(() => {});
    refresh();
  } catch (e) { status(`保存失败：${e.message}`, true); }
}

async function stats() {
  const st = await j("/api/touch/stats");
  $("stats").className = st.total ? "" : "empty";
  $("stats").innerHTML = st.total ? `<p>共 ${st.total} 次触摸，误触率 ${(st.miss_rate * 100).toFixed(1)}%</p><table><tr><th>键</th><th>次数</th><th>误触</th><th>偏移 dx/dy</th><th>按住 ms</th></tr>` +
    st.keys.slice(0, 15).map((k) => `<tr><td>${k.key ?? "空白"}</td><td>${k.count}</td><td>${(k.miss_rate * 100).toFixed(0)}%</td><td>${k.avg_dx}/${k.avg_dy}</td><td>${k.avg_ms}</td></tr>`).join("") + "</table>"
    : "暂无触摸数据，在键盘上打几个字试试";
  const pts = (await j("/api/touch/points?limit=3000")).points, c = $("heat").getContext("2d");
  c.clearRect(0, 0, 960, 540);
  c.fillStyle = "#0f1526";
  S.keys.forEach((k) => { c.beginPath(); c.roundRect ? c.roundRect(k.rect[0] / 2, k.rect[1] / 2, k.rect[2] / 2, k.rect[3] / 2, 5) : c.rect(k.rect[0] / 2, k.rect[1] / 2, k.rect[2] / 2, k.rect[3] / 2); c.fill(); });
  pts.forEach(([x, y, hit]) => { c.fillStyle = hit ? "rgba(74,222,128,.35)" : "rgba(248,113,113,.6)"; c.beginPath(); c.arc(x / 2, y / 2, 5, 0, 7); c.fill(); });
}

async function upload(input, path) {
  const files = input.files;
  if (!files.length) return status("先选择图片", true);
  const fd = new FormData();
  [...files].forEach((f) => fd.append("file", f, f.name));
  status("上传中…");
  try {
    const r = await (await fetch(B + path, { method: "POST", body: fd })).json();
    if (!r.ok) throw new Error(r.error);
    input.value = "";
    if (r.anim && Object.keys(r.anim).length) status("已上传，板子正在解码动态壁纸，完成后自动显示…");
    return r.saved;
  }
  catch (e) { status(`上传失败：${e.message}`, true); }
}

$("up").onclick = async () => { const s = await upload($("file"), "/api/wallpapers"); if (s) put({ wallpaper: s[0] }); };
$("fxup").onclick = async () => { const s = await upload($("fxfile"), "/api/effects"); if (s) put({ effect_image: s[0], effect: "image" }, true); };
$("fxcolor").oninput = () => { $("fxtheme").checked = false; };
$("fxcolor").onchange = () => put({ effect_color: $("fxcolor").value }, true);
$("fxtheme").onchange = () => put({ effect_color: $("fxtheme").checked ? "" : $("fxcolor").value }, true);
$("fxms").oninput = () => { $("fxmsv").textContent = `${$("fxms").value} ms`; };
$("fxms").onchange = () => put({ effect_ms: +$("fxms").value }, true);
$("pv").onclick = () => j("/api/effects/preview", { method: "POST", body: JSON.stringify({ key: $("pvkey").value }) }).catch((e) => status(e.message, true));
$("keadd").onclick = () => put({ key_effects: { ...(P.key_effects || {}), [$("kekey").value]: $("keval").value } });
$("prof").onchange = (e) => { sel = e.target.value; refresh(); };
$("act").onclick = () => j(`/api/active/${enc(sel)}`, { method: "POST" }).then(refresh);
$("add").onclick = () => { const n = $("newp").value.trim().toLowerCase(); if (n) { sel = n; put({}); $("newp").value = ""; } };
$("save").onclick = () => {
  let legends;
  try { legends = JSON.parse($("legend").value || "{}"); } catch { return status("键帽文字不是合法 JSON", true); }
  put({ theme: $("theme").value, opacity: +$("op").value, legends });
};

function live() {
  const ws = new WebSocket(B.replace(/^http/, "ws") + "/ws/events");
  ws.onopen = refresh;  // board restarted (deploy / systemd) -> reload state instead of staying on "连接中"
  ws.onmessage = (m) => { const e = JSON.parse(m.data); if (e.type === "touch") stats(); else if (e.type !== "free" && e.type !== "bar") refresh(); };
  ws.onclose = () => setTimeout(live, 2000);
}
setInterval(() => { if (!document.hidden) $("shot").src = `${B}/api/screenshot?fmt=jpg&t=${Date.now()}`; }, 1000);
// ---- Agnes: one turn through the panel's /api/agnes (AGH print mode) ----
const esc = (s) => String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
let busy = false;
async function ask(prompt) {
  if (busy || !prompt) return;
  busy = true; $("agnesGo").disabled = true;
  const log = $("agnesLog"); log.className = "";
  log.innerHTML = `<div class="step"><span class="think"></span>Agnes 正在读取设备并思考…（通常 20–60 秒）</div>`;
  $("agnesMeta").textContent = "";
  const t0 = Date.now(), tick = setInterval(() => { $("agnesMeta").textContent = `${((Date.now() - t0) / 1000) | 0} s`; }, 1000);
  try {
    const r = await (await fetch("/api/agnes", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt }) })).json();
    const steps = (r.steps || []).filter((s) => s.includes("·")).map((s) => `<div class="step">⚙ ${esc(s)}</div>`).join("");
    log.innerHTML = steps + `<div class="ans">${r.ok ? esc(r.text || "(无文本回复)") : '<span class="err">' + esc(r.error || "失败") + "</span>\n" + esc(r.text || "")}</div>`;
    $("agnesMeta").textContent = `用时 ${r.seconds ?? ((Date.now() - t0) / 1000).toFixed(1)} s · ${(r.steps || []).filter((s) => s.includes("·")).length} 次工具调用`;
    await refresh();
  } catch (e) {
    log.innerHTML = `<span class="err">面板不可达：${esc(e.message)}。请确认 desktop/panel.py 正在运行。</span>`;
  } finally { clearInterval(tick); busy = false; $("agnesGo").disabled = false; }
}
document.querySelectorAll("[data-ask]").forEach((b) => (b.onclick = () => { $("agnesIn").value = b.dataset.ask; ask(b.dataset.ask); }));
$("agnesGo").onclick = () => ask($("agnesIn").value.trim());
$("agnesIn").onkeydown = (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) ask($("agnesIn").value.trim()); };

refresh(); live();
