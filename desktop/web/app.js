const B = window.BOARD || "http://127.0.0.1:8765";
const $ = (id) => document.getElementById(id);
let S = null, sel = null;

async function j(path, opt = {}) {
  const r = await fetch(B + path, { headers: { "Content-Type": "application/json" }, ...opt });
  const d = await r.json();
  if (!d.ok) throw new Error(d.error || r.status);
  return d;
}
const status = (t, bad) => { $("status").textContent = t; $("status").className = bad ? "err" : ""; };

async function refresh() {
  try {
    S = await j("/api/state");
    status(`已连接 ${B} · 当前 ${S.active} · 映射延迟 ${S.latency_ms ?? "-"} ms`);
  } catch (e) { return status(`连不上键盘 ${B}：${e.message}`, true); }
  sel = sel && S.profiles.includes(sel) ? sel : S.active;
  $("prof").innerHTML = S.profiles.map((p) => `<option ${p === sel ? "selected" : ""}>${p}</option>`).join("");
  const p = (await j(`/api/profile/${sel}`)).profile;
  $("theme").value = p.theme; $("op").value = p.opacity; $("legend").value = JSON.stringify(p.legends);
  $("walls").innerHTML = S.wallpapers.length ? S.wallpapers.map((w) =>
    `<figure class="${w === p.wallpaper ? "on" : ""}" data-w="${w}"><img loading="lazy" src="${B}/api/wallpapers/${encodeURIComponent(w)}"><figcaption>${w}</figcaption></figure>`).join("")
    : `<div class="empty">还没有壁纸，先上传一张 16:9 图片</div>`;
  document.querySelectorAll(".walls figure").forEach((f) => f.onclick = () => put({ wallpaper: f.dataset.w }));
  stats();
}

async function put(body) {
  try { await j(`/api/profile/${sel}`, { method: "PUT", body: JSON.stringify(body) }); refresh(); }
  catch (e) { status(`保存失败：${e.message}`, true); }
}

async function stats() {
  const st = await j("/api/touch/stats");
  $("stats").className = st.total ? "" : "empty";
  $("stats").innerHTML = st.total ? `<p>共 ${st.total} 次触摸，误触率 ${(st.miss_rate * 100).toFixed(1)}%</p><table><tr><th>键</th><th>次数</th><th>误触</th><th>偏移 dx/dy</th><th>按压 ms</th></tr>` +
    st.keys.slice(0, 15).map((k) => `<tr><td>${k.key ?? "空白"}</td><td>${k.count}</td><td>${(k.miss_rate * 100).toFixed(0)}%</td><td>${k.avg_dx}/${k.avg_dy}</td><td>${k.avg_ms}</td></tr>`).join("") + "</table>"
    : "暂无触摸数据，在键盘上打几个字试试";
  const pts = (await j("/api/touch/points?limit=3000")).points, c = $("heat").getContext("2d");
  c.clearRect(0, 0, 960, 540);
  c.strokeStyle = "#26304a";
  S.keys.forEach((k) => c.strokeRect(k.rect[0] / 2, k.rect[1] / 2, k.rect[2] / 2, k.rect[3] / 2));
  pts.forEach(([x, y, hit]) => { c.fillStyle = hit ? "rgba(74,222,128,.35)" : "rgba(248,113,113,.6)"; c.beginPath(); c.arc(x / 2, y / 2, 6, 0, 7); c.fill(); });
}

$("up").onclick = async () => {
  const files = $("file").files;
  if (!files.length) return status("先选择图片", true);
  const fd = new FormData();
  [...files].forEach((f) => fd.append("file", f, f.name));
  status("上传中…");
  try { const r = await (await fetch(B + "/api/wallpapers", { method: "POST", body: fd })).json(); if (!r.ok) throw new Error(r.error); refresh(); }
  catch (e) { status(`上传失败：${e.message}`, true); }
};
$("prof").onchange = (e) => { sel = e.target.value; refresh(); };
$("act").onclick = () => j(`/api/active/${sel}`, { method: "POST" }).then(refresh);
$("add").onclick = () => { const n = $("newp").value.trim().toLowerCase(); if (n) { sel = n; put({}); $("newp").value = ""; } };
$("save").onclick = () => {
  let legends;
  try { legends = JSON.parse($("legend").value || "{}"); } catch { return status("键帽文字不是合法 JSON", true); }
  put({ theme: $("theme").value, opacity: +$("op").value, legends });
};

function live() {
  const ws = new WebSocket(B.replace(/^http/, "ws") + "/ws/events");
  ws.onopen = refresh;  // board restarted (deploy / systemd) -> reload state instead of staying on "连接中"
  ws.onmessage = (m) => { const e = JSON.parse(m.data); if (e.type === "touch") stats(); else refresh(); };
  ws.onclose = () => setTimeout(live, 2000);
}
setInterval(() => { $("shot").src = `${B}/api/screenshot?t=${Date.now()}`; }, 1000);
refresh(); live();
