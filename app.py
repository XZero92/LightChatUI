#!/usr/bin/env python3
"""Light Chat — 단일 스크립트 OpenAI 호환 채팅 UI.

이 파일 하나로 끝난다. UI(HTML/CSS/JS)는 아래 HTML 상수에 내장되어 있고,
같은 프로세스가 정적 UI 서빙과 API 프록시를 함께 담당한다. 브라우저는 동일
출처(localhost)의 /proxy 로만 요청하므로 CORS / origin=null 문제가 없고,
프록시가 브라우저 형태의 User-Agent를 붙여 Cloudflare 등의 봇 차단도 피한다.

웹 UI와 터미널(TUI)이 한 파일에서 공존한다. provider 호출 로직(core)을
공유하며, 실행 인자로 모드를 고른다. 의존성 없음(표준 라이브러리만).

    python app.py [PORT]      # 웹 UI (기본 8000), 실행 시 브라우저 자동 오픈
    python app.py --tui       # 터미널 채팅 (서버·프록시 불필요)
    python app.py --help

TUI 모드는 환경변수로 설정을 미리 지정할 수 있다(없으면 실행 중 입력):
    LC_BASE_URL, LC_API_KEY, LC_MODEL, LC_SYSTEM, LC_TEMPERATURE
"""
import sys
import os
import json
import time
import shutil
import threading
import webbrowser
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def configure_text_output():
    """Windows 레거시 콘솔에서 도움말/로그 출력이 인코딩 오류로 멈추지 않게 한다."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")


# 프록시가 업스트림으로 전달할 요청 헤더
FORWARD_HEADERS = ("Authorization", "Content-Type", "Accept")
API_TIMEOUT = 600
DEFAULT_BASE_URL = "https://api.openai.com/v1"
MODELS_PATH = "/models"
CHAT_COMPLETIONS_PATH = "/chat/completions"
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0.0.0 Safari/537.36")

# ---------------------------------------------------------------------------
# 내장 UI  (raw 문자열: JS 정규식의 백슬래시를 그대로 보존)
# ---------------------------------------------------------------------------
HTML = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Light Chat</title>
<style>
  :root {
    --bg: #1e1e22;
    --panel: #27272d;
    --border: #3a3a42;
    --text: #e6e6e9;
    --muted: #9a9aa3;
    --accent: #6d8cff;
    --user-bg: #34344a;
    --assist-bg: #2c2c33;
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Malgun Gothic", sans-serif;
    background: var(--bg);
    color: var(--text);
    display: flex;
    flex-direction: column;
    height: 100vh;
  }
  header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px;
    background: var(--panel);
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }
  header h1 { font-size: 15px; margin: 0; font-weight: 600; flex: 1; }
  header .status { font-size: 12px; color: var(--muted); }
  button {
    background: var(--accent);
    color: #fff;
    border: none;
    border-radius: 6px;
    padding: 7px 12px;
    font-size: 13px;
    cursor: pointer;
  }
  button:hover { filter: brightness(1.1); }
  button.ghost { background: transparent; color: var(--muted); border: 1px solid var(--border); }
  button:disabled { opacity: 0.5; cursor: default; }

  #settings {
    background: var(--panel);
    border-bottom: 1px solid var(--border);
    padding: 12px 14px;
    display: none;
    grid-template-columns: 100px 1fr;
    gap: 8px 10px;
    align-items: center;
  }
  #settings.open { display: grid; }
  #settings label { font-size: 13px; color: var(--muted); }
  #settings input, #settings textarea {
    background: var(--bg);
    border: 1px solid var(--border);
    color: var(--text);
    border-radius: 6px;
    padding: 7px 9px;
    font-size: 13px;
    width: 100%;
    font-family: inherit;
  }
  #settings textarea { resize: vertical; min-height: 50px; }
  .model-row { display: flex; gap: 6px; align-items: center; }
  .combo { position: relative; flex: 1; display: flex; }
  .combo input { flex: 1; padding-right: 28px; }
  .combo-toggle {
    position: absolute; right: 1px; top: 1px; bottom: 1px; width: 26px;
    background: transparent; border: none; color: var(--muted);
    cursor: pointer; padding: 0; font-size: 11px;
  }
  .combo-toggle:hover { color: var(--text); }
  .combo-list {
    position: absolute; top: calc(100% + 3px); left: 0; right: 0;
    max-height: 220px; overflow-y: auto; margin: 0; padding: 4px;
    list-style: none; background: var(--panel); border: 1px solid var(--border);
    border-radius: 6px; z-index: 20; display: none;
    box-shadow: 0 6px 18px rgba(0,0,0,0.45);
  }
  .combo-list.open { display: block; }
  .combo-list li {
    padding: 7px 9px; border-radius: 4px; font-size: 13px; cursor: pointer;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .combo-list li:hover, .combo-list li.active { background: var(--accent); color: #fff; }
  .combo-list li.empty { color: var(--muted); cursor: default; }
  .combo-list li.empty:hover { background: transparent; color: var(--muted); }
  #refreshModels { padding: 7px 10px; font-size: 14px; line-height: 1; flex-shrink: 0; }
  #refreshModels .ic { display: inline-block; }
  #refreshModels.spin .ic { animation: spin 0.8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }

  #messages {
    flex: 1;
    overflow-y: auto;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .msg { max-width: 760px; width: 100%; margin: 0 auto; display: flex; gap: 10px; }
  .msg .role {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--muted);
    flex-shrink: 0;
    width: 64px;
    padding-top: 2px;
  }
  .msg .bubble {
    flex: 1;
    background: var(--assist-bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px 12px;
    white-space: pre-wrap;
    word-break: break-word;
    line-height: 1.55;
    font-size: 14px;
  }
  .msg.user .bubble { background: var(--user-bg); }
  .msg.error .bubble { border-color: #c0504d; color: #ff9b97; }
  .bubble pre {
    background: #18181c;
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 10px;
    overflow-x: auto;
    margin: 6px 0;
  }
  .bubble code { font-family: "Consolas", "Courier New", monospace; font-size: 13px; }
  .bubble .metrics { margin-top: 6px; padding-top: 4px; border-top: 1px solid var(--border); font-size: 11px; color: var(--muted); }

  footer {
    flex-shrink: 0;
    border-top: 1px solid var(--border);
    background: var(--panel);
    padding: 10px 14px;
  }
  #inputRow { max-width: 760px; margin: 0 auto; display: flex; gap: 8px; align-items: flex-end; }
  #input {
    flex: 1;
    background: var(--bg);
    border: 1px solid var(--border);
    color: var(--text);
    border-radius: 8px;
    padding: 10px 12px;
    font-size: 14px;
    font-family: inherit;
    resize: none;
    max-height: 200px;
    line-height: 1.5;
  }
  #input:focus, #settings input:focus, #settings textarea:focus { outline: 1px solid var(--accent); border-color: var(--accent); }
  .hint { max-width: 760px; margin: 6px auto 0; font-size: 11px; color: var(--muted); }
</style>
</head>
<body>
  <header>
    <h1>Light Chat</h1>
    <span class="status" id="status"></span>
    <button class="ghost" id="clearBtn">대화 지우기</button>
    <button class="ghost" id="settingsBtn">⚙ 설정</button>
  </header>

  <div id="settings">
    <label for="baseUrl">Base URL</label>
    <input id="baseUrl" placeholder="https://api.openai.com/v1" autocomplete="off" />
    <label for="apiKey">API Key</label>
    <input id="apiKey" type="password" placeholder="sk-..." autocomplete="off" />
    <label for="model">Model</label>
    <div class="model-row">
      <div class="combo" id="modelCombo">
        <input id="model" placeholder="gpt-4o-mini" autocomplete="off" />
        <button type="button" class="combo-toggle" id="modelToggle" title="목록 열기">▾</button>
        <ul class="combo-list" id="modelList"></ul>
      </div>
      <button class="ghost" id="refreshModels" title="모델 새로고침 / 연결 테스트"><span class="ic">↻</span></button>
    </div>
    <label for="system">System</label>
    <textarea id="system" placeholder="(선택) 시스템 프롬프트"></textarea>
    <label for="temperature">Temperature</label>
    <input id="temperature" type="number" step="0.1" min="0" max="2" placeholder="0.7" />
  </div>

  <div id="messages"></div>

  <footer>
    <div id="inputRow">
      <textarea id="input" rows="1" placeholder="메시지를 입력하세요  (Enter 전송 / Shift+Enter 줄바꿈)"></textarea>
      <button id="sendBtn">전송</button>
    </div>
    <div class="hint">API 키·설정·대화기록은 이 탭의 sessionStorage에만 보관되며, <b>탭을 닫으면 모두 사라집니다</b>. 외부로 전송되지 않습니다.</div>
  </footer>

<script>
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const els = {
    messages: $("messages"), input: $("input"), send: $("sendBtn"),
    clear: $("clearBtn"), settingsBtn: $("settingsBtn"), settings: $("settings"),
    status: $("status"),
    baseUrl: $("baseUrl"), apiKey: $("apiKey"), model: $("model"),
    system: $("system"), temperature: $("temperature"),
    modelList: $("modelList"), refreshModels: $("refreshModels"),
    modelCombo: $("modelCombo"), modelToggle: $("modelToggle"),
  };

  const SETTINGS_KEYS = ["baseUrl", "apiKey", "model", "system", "temperature"];
  const DEFAULTS = { baseUrl: "https://api.openai.com/v1", temperature: "0.7" };

  // http(s)로 서빙되면(프록시 경유) 동일 출처 /proxy 로 요청해 CORS·origin=null 문제를 피한다.
  // file:// 로 직접 열면 업스트림으로 직접 호출(서버가 CORS를 허용하는 경우에만 동작).
  const VIA_PROXY = location.protocol === "http:" || location.protocol === "https:";
  function apiFetch(path, opts) {
    opts = opts || {};
    const target = els.baseUrl.value.replace(/\/+$/, "") + path;
    if (VIA_PROXY) {
      const headers = Object.assign({}, opts.headers || {}, { "X-Target-URL": target });
      return fetch("/proxy", Object.assign({}, opts, { headers }));
    }
    return fetch(target, opts);
  }

  // --- settings persistence ---
  function loadSettings() {
    SETTINGS_KEYS.forEach((k) => {
      const v = sessionStorage.getItem("lc_" + k);
      els[k].value = v !== null ? v : (DEFAULTS[k] || "");
    });
  }
  function saveSettings() {
    SETTINGS_KEYS.forEach((k) => sessionStorage.setItem("lc_" + k, els[k].value));
  }
  SETTINGS_KEYS.forEach((k) => els[k].addEventListener("input", saveSettings));

  // --- model list (custom combobox) ---
  let MODELS = [];
  let activeIdx = -1;

  function renderOptions(filter) {
    const f = (filter || "").toLowerCase();
    const matches = MODELS.filter((id) => id.toLowerCase().includes(f));
    els.modelList.innerHTML = "";
    activeIdx = -1;
    if (!MODELS.length) {
      els.modelList.innerHTML = '<li class="empty">목록 없음 — ↻ 로 불러오세요</li>';
      return;
    }
    if (!matches.length) {
      els.modelList.innerHTML = '<li class="empty">일치하는 모델 없음</li>';
      return;
    }
    matches.forEach((id) => {
      const li = document.createElement("li");
      li.textContent = id;
      li.addEventListener("mousedown", (e) => {
        e.preventDefault(); // blur 보다 먼저 처리
        els.model.value = id;
        saveSettings();
        closeList();
      });
      els.modelList.appendChild(li);
    });
  }

  function openList(filter) {
    renderOptions(filter !== undefined ? filter : els.model.value);
    els.modelList.classList.add("open");
  }
  function closeList() {
    els.modelList.classList.remove("open");
    activeIdx = -1;
  }
  function isOpen() { return els.modelList.classList.contains("open"); }

  function moveActive(delta) {
    const items = els.modelList.querySelectorAll("li:not(.empty)");
    if (!items.length) return;
    if (activeIdx >= 0 && items[activeIdx]) items[activeIdx].classList.remove("active");
    activeIdx = (activeIdx + delta + items.length) % items.length;
    items[activeIdx].classList.add("active");
    items[activeIdx].scrollIntoView({ block: "nearest" });
  }

  els.modelToggle.addEventListener("mousedown", (e) => {
    e.preventDefault();
    if (isOpen()) { closeList(); } else { els.model.focus(); openList(""); }
  });
  els.model.addEventListener("focus", () => openList(""));  // 펼칠 땐 입력값과 무관하게 전체 표시
  els.model.addEventListener("input", () => { saveSettings(); openList(els.model.value); });
  els.model.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); if (!isOpen()) openList(""); else moveActive(1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); moveActive(-1); }
    else if (e.key === "Enter") {
      const items = els.modelList.querySelectorAll("li:not(.empty)");
      if (isOpen() && activeIdx >= 0 && items[activeIdx]) {
        e.preventDefault();
        els.model.value = items[activeIdx].textContent;
        saveSettings();
        closeList();
      }
    } else if (e.key === "Escape") { closeList(); }
  });
  document.addEventListener("mousedown", (e) => {
    if (!els.modelCombo.contains(e.target)) closeList();
  });

  function parseModels(json) {
    return (json.data || json.models || [])
      .map((m) => (typeof m === "string" ? m : m.id || m.name))
      .filter(Boolean)
      .sort((a, b) => a.localeCompare(b));
  }

  // manual=true(↻ 클릭): 연결 테스트를 겸해 ✓/✗ 를 명확히 보고 + 빈 칸 검증.
  // manual=false(타이핑 디바운스·로드 시 자동): 조용히 목록만 채움.
  async function fetchModels(manual) {
    if (!hasModelSettings()) {
      if (manual) {
        openSettingsWithStatus("Base URL·API Key 를 먼저 입력하세요");
      }
      return;
    }
    els.refreshModels.classList.add("spin");
    if (manual) setStatus("연결 확인 중…");
    try {
      const res = await apiFetch("/models", {
        headers: { "Authorization": "Bearer " + els.apiKey.value },
      });
      if (!res.ok) {
        const t = manual ? await res.text() : "";
        throw new Error("HTTP " + res.status + (t ? " — " + t.slice(0, 120) : ""));
      }
      MODELS = parseModels(await res.json());
      setStatus(manual
        ? "✓ 연결 정상 (" + MODELS.length + "개 모델)"
        : (MODELS.length ? MODELS.length + "개 모델 로드됨" : "모델 없음"));
      if (isOpen()) openList("");
    } catch (e) {
      setStatus((manual ? "✗ 연결 실패: " : "모델 목록 실패: ") + (e.message || e));
    } finally {
      els.refreshModels.classList.remove("spin");
    }
  }

  let modelFetchTimer = null;
  function scheduleFetchModels() {
    clearTimeout(modelFetchTimer);
    modelFetchTimer = setTimeout(fetchModels, 600);
  }
  els.baseUrl.addEventListener("input", scheduleFetchModels);
  els.apiKey.addEventListener("input", scheduleFetchModels);
  els.refreshModels.addEventListener("click", () => fetchModels(true));

  els.settingsBtn.addEventListener("click", () => {
    els.settings.classList.toggle("open");  // 키 없어도 자유롭게 열고 닫기
  });

  // --- conversation state ---
  let history = JSON.parse(sessionStorage.getItem("lc_history") || "[]");
  function saveHistory() { sessionStorage.setItem("lc_history", JSON.stringify(history)); }

  function setStatus(text) {
    els.status.textContent = text;
  }

  function openSettingsWithStatus(text) {
    els.settings.classList.add("open");
    setStatus(text);
  }

  function renderInline(text) {
    // minimal: escape HTML, then render ``` code blocks and `inline code`
    const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    const parts = text.split(/(```[\s\S]*?```)/g);
    return parts.map((p) => {
      if (p.startsWith("```") && p.endsWith("```")) {
        const body = p.slice(3, -3).replace(/^[^\n]*\n/, "");
        return "<pre><code>" + esc(body) + "</code></pre>";
      }
      return esc(p).replace(/`([^`]+)`/g, "<code>$1</code>");
    }).join("");
  }

  function addBubble(role, text, cls, metrics) {
    const wrap = document.createElement("div");
    wrap.className = "msg " + (cls || role);
    const r = document.createElement("div");
    r.className = "role";
    r.textContent = role === "user" ? "나" : (cls === "error" ? "오류" : "AI");
    const b = document.createElement("div");
    b.className = "bubble";
    b.innerHTML = renderInline(text);
    if (metrics) addMetrics(b, metrics);
    wrap.appendChild(r); wrap.appendChild(b);
    els.messages.appendChild(wrap);
    els.messages.scrollTop = els.messages.scrollHeight;
    return b;
  }

  function addMetrics(bubble, text) {
    const el = document.createElement("div");
    el.className = "metrics";
    el.textContent = text;
    bubble.appendChild(el);
  }

  function renderHistory() {
    els.messages.innerHTML = "";
    history.forEach((m) => addBubble(m.role, m.content, null, m.metrics));
  }

  // 서버 usage 있으면 정확, 없으면 청크 수로 근사(~). TTFT 는 항상 정확.
  function metricsText(t0, firstAt, chunks, usageTok) {
    if (firstAt === null) return "";
    const ttft = (firstAt - t0) / 1000;
    const gen = (performance.now() - firstAt) / 1000;
    const toks = usageTok != null ? usageTok : chunks;
    const approx = usageTok == null;
    let s = "TTFT " + ttft.toFixed(2) + "s · " + (approx ? "~" : "") + toks + " tok";
    if (gen > 0 && toks > 0) s += " · " + (toks / gen).toFixed(1) + " tok/s";
    return s;
  }

  function hasModelSettings() {
    return !!(els.baseUrl.value && els.apiKey.value);
  }

  function hasChatSettings() {
    return !!(els.baseUrl.value && els.apiKey.value && els.model.value);
  }

  function buildRequestMessages() {
    const msgs = [];
    const system = els.system.value.trim();
    if (system) msgs.push({ role: "system", content: system });
    history.forEach((m) => msgs.push({ role: m.role, content: m.content }));
    return msgs;
  }

  function buildChatBody(messages) {
    const body = {
      model: els.model.value,
      messages,
      stream: true,
      stream_options: { include_usage: true },
    };
    const temp = parseFloat(els.temperature.value);
    if (!isNaN(temp)) body.temperature = temp;
    return body;
  }

  function extractDelta(json) {
    return json.choices?.[0]?.delta?.content || "";
  }

  async function readChatStream(res, onDelta) {
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    let usageTok = null;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split("\n");
      buf = lines.pop();
      for (const line of lines) {
        const t = line.trim();
        if (!t.startsWith("data:")) continue;
        const data = t.slice(5).trim();
        if (data === "[DONE]") continue;
        try {
          const json = JSON.parse(data);
          if (json.usage && typeof json.usage.completion_tokens === "number") {
            usageTok = json.usage.completion_tokens;
          }
          const delta = extractDelta(json);
          if (delta) onDelta(delta);
        } catch (_) { /* ignore partial */ }
      }
    }
    return usageTok;
  }

  // --- sending ---
  let controller = null;

  async function send() {
    const text = els.input.value.trim();
    if (!text || controller) return;

    if (!hasChatSettings()) {
      openSettingsWithStatus("Base URL · API Key · Model 을 먼저 입력하세요");
      return;
    }

    history.push({ role: "user", content: text });
    addBubble("user", text);
    saveHistory();
    els.input.value = "";
    els.input.style.height = "auto";

    const bubble = addBubble("assistant", "");
    let acc = "";
    controller = new AbortController();
    els.send.textContent = "중지";
    setStatus("응답 중…");

    const t0 = performance.now();
    let firstAt = null, chunks = 0;
    try {
      const res = await apiFetch("/chat/completions", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": "Bearer " + els.apiKey.value,
        },
        body: JSON.stringify(buildChatBody(buildRequestMessages())),
        signal: controller.signal,
      });

      if (!res.ok) {
        const errText = await res.text();
        throw new Error("HTTP " + res.status + ": " + errText.slice(0, 500));
      }

      const usageTok = await readChatStream(res, (delta) => {
        if (firstAt === null) firstAt = performance.now();
        chunks++;
        acc += delta;
        bubble.innerHTML = renderInline(acc);
        els.messages.scrollTop = els.messages.scrollHeight;
      });

      const mtext = metricsText(t0, firstAt, chunks, usageTok);
      if (mtext) addMetrics(bubble, mtext);
      history.push({ role: "assistant", content: acc, metrics: mtext });
      saveHistory();
      setStatus("");
    } catch (e) {
      if (e.name === "AbortError") {
        if (acc) { history.push({ role: "assistant", content: acc }); saveHistory(); }
        setStatus("중지됨");
      } else {
        bubble.parentElement.className = "msg error";
        bubble.previousSibling.textContent = "오류";
        bubble.innerHTML = renderInline(String(e.message || e));
        setStatus("오류");
      }
    } finally {
      controller = null;
      els.send.textContent = "전송";
    }
  }

  els.send.addEventListener("click", () => {
    if (controller) { controller.abort(); } else { send(); }
  });

  els.input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  });
  els.input.addEventListener("input", () => {
    els.input.style.height = "auto";
    els.input.style.height = Math.min(els.input.scrollHeight, 200) + "px";
  });

  els.clear.addEventListener("click", () => {
    history = [];
    saveHistory();
    renderHistory();
    setStatus("");
  });

  // --- init ---
  loadSettings();
  renderHistory();
  if (!els.apiKey.value) els.settings.classList.add("open");
  if (hasModelSettings()) fetchModels();
})();
</script>
</body>
</html>
"""

HTML_BYTES = HTML.encode("utf-8")


# ---------------------------------------------------------------------------
# 공유 코어 — 업스트림(OpenAI 호환 API) 호출. 웹 프록시·TUI가 함께 쓴다.
# 브라우저 형태의 User-Agent를 붙여 Cloudflare 등의 봇 차단을 피한다.
# ---------------------------------------------------------------------------
def api_url(base, path):
    return base.rstrip("/") + path


def encode_json(obj):
    return json.dumps(obj).encode("utf-8")


def model_id(item):
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return item.get("id") or item.get("name")
    return None


def extract_model_ids(data):
    items = data.get("data") or data.get("models") or []
    return sorted(v for v in (model_id(item) for item in items) if v)


def build_chat_payload(model, messages, temperature=None):
    payload = {"model": model, "messages": messages, "stream": True,
               "stream_options": {"include_usage": True}}
    if temperature is not None:
        payload["temperature"] = temperature
    return payload


def iter_sse_json(resp):
    for raw in resp:
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            continue
        chunk = line[5:].strip()
        if chunk == "[DONE]":
            break
        try:
            yield json.loads(chunk)
        except ValueError:
            continue  # 부분 수신 무시


def extract_chat_delta(obj):
    try:
        return obj["choices"][0]["delta"].get("content")
    except (KeyError, IndexError, AttributeError, TypeError):
        return None


def open_upstream(url, api_key=None, data=None, method="GET", content_type=None):
    req = urllib.request.Request(url, data=data, method=method)
    if api_key:
        req.add_header("Authorization", "Bearer " + api_key)
    if content_type:
        req.add_header("Content-Type", content_type)
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", BROWSER_UA)
    return urllib.request.urlopen(req, timeout=API_TIMEOUT)


def list_models(base, key):
    """GET {base}/models → 정렬된 모델 id 리스트."""
    with open_upstream(api_url(base, MODELS_PATH), key) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return extract_model_ids(data)


def chat_stream(base, key, model, messages, temperature=None, stats=None):
    """POST {base}/chat/completions (stream) → 토큰(content) 제너레이터.
    stats(dict)를 주면 서버가 보낸 usage 를 stats['usage'] 에 채운다."""
    data = encode_json(build_chat_payload(model, messages, temperature))
    with open_upstream(api_url(base, CHAT_COMPLETIONS_PATH), key, data=data,
                       method="POST", content_type="application/json") as resp:
        for obj in iter_sse_json(resp):
            if stats is not None and isinstance(obj.get("usage"), dict):
                stats["usage"] = obj["usage"]          # 서버 제공 정확 토큰 수
            delta = extract_chat_delta(obj)
            if delta:
                yield delta


def _fmt_metrics(t0, first_at, end, chunks, usage):
    """TTFT/TPS 한 줄 문자열. 서버 usage 있으면 정확, 없으면 청크 수로 근사(~)."""
    if first_at is None:
        return ""
    ttft = first_at - t0
    gen = end - first_at
    toks = usage.get("completion_tokens") if isinstance(usage, dict) else None
    approx = toks is None
    if toks is None:
        toks = chunks
    line = "TTFT %.2fs · %s%d tok" % (ttft, "~" if approx else "", toks)
    if gen > 0 and toks > 0:
        line += " · %.1f tok/s" % (toks / gen)
    return line


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"  # 연결 종료로 스트림 끝을 표시(청크 인코딩 불필요)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # --- 내장 UI ---
    def _serve_ui(self):
        self._send_bytes(200, "text/html; charset=utf-8", HTML_BYTES)

    def _send_bytes(self, code, content_type, payload):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, code, obj):
        self._send_bytes(code, "application/json", encode_json(obj))

    def _request_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        return self.rfile.read(length) if length else None

    def _proxy_request(self, target, body):
        req = urllib.request.Request(target, data=body, method=self.command)
        for h in FORWARD_HEADERS:
            v = self.headers.get(h)
            if v:
                req.add_header(h, v)
        # Cloudflare 등 일부 게이트웨이는 Python-urllib 기본 UA를 403으로 차단하므로
        # 브라우저 형태의 User-Agent를 사용한다.
        req.add_header("User-Agent", BROWSER_UA)
        return req

    def _send_http_error(self, err):
        payload = err.read()
        content_type = err.headers.get("Content-Type", "application/json")
        self._send_bytes(err.code, content_type, payload)

    def _stream_response(self, resp):
        self.send_response(resp.status)
        self.send_header("Content-Type", resp.headers.get("Content-Type", "application/octet-stream"))
        self.end_headers()
        try:
            for line in resp:          # 라인 단위로 즉시 전달 → SSE 스트리밍 유지
                self.wfile.write(line)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass  # 클라이언트가 중지함

    # --- API 프록시 (GET=models, POST=chat/completions 등) ---
    def _proxy(self):
        target = self.headers.get("X-Target-URL")
        if not target:
            self._json(400, {"error": "Missing X-Target-URL header"})
            return

        req = self._proxy_request(target, self._request_body())

        try:
            with urllib.request.urlopen(req, timeout=API_TIMEOUT) as resp:
                self._stream_response(resp)
        except urllib.error.HTTPError as e:
            self._send_http_error(e)
        except Exception as e:  # 연결 실패 등
            self._json(502, {"error": "Upstream request failed: %s" % e})

    def do_GET(self):
        if self.path == "/proxy":
            self._proxy()
        elif self.path in ("/", "/index.html"):
            self._serve_ui()
        else:
            self.send_error(404, "Not found")

    def do_POST(self):
        if self.path == "/proxy":
            self._proxy()
        else:
            self.send_error(404, "Not found")


# ---------------------------------------------------------------------------
# 웹 모드
# ---------------------------------------------------------------------------
def run_web(port):
    url = "http://localhost:%d" % port
    print("Light Chat (web)  ->  %s" % url)
    print("(Ctrl+C 로 종료)")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\n종료되었습니다.")


# ---------------------------------------------------------------------------
# TUI 모드 — 서버·프록시 없이 core 를 직접 호출한다(브라우저가 아니므로 CORS 무관).
# ---------------------------------------------------------------------------
def _enable_ansi():
    """Windows 콘솔에서 ANSI 색상 활성화. 실패하면 색 없이 동작."""
    if os.name != "nt":
        return True
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not k.GetConsoleMode(h, ctypes.byref(mode)):
            return False
        k.SetConsoleMode(h, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        return True
    except Exception:
        return False


def _read_key():
    """키 입력 1개를 정규화: 'up'/'down'/'enter'/'backspace'/'esc'/'ctrl-c'
    또는 출력 가능한 단일 문자. stdlib만 사용(Windows=msvcrt, Unix=termios)."""
    if os.name == "nt":
        import msvcrt
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):                 # 특수키(화살표 등) 접두
            code = msvcrt.getwch()
            return {"H": "up", "P": "down", "K": "left", "M": "right"}.get(code, "")
        return {"\r": "enter", "\x08": "backspace",
                "\x1b": "esc", "\x03": "ctrl-c"}.get(ch, ch)
    import termios, tty, select                     # Unix
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":                            # Esc 단독 또는 화살표 시퀀스
            if select.select([sys.stdin], [], [], 0.001)[0]:
                seq = sys.stdin.read(2)
                return {"[A": "up", "[B": "down", "[C": "right", "[D": "left"}.get(seq, "esc")
            return "esc"
        return {"\r": "enter", "\n": "enter", "\x7f": "backspace",
                "\x08": "backspace", "\x03": "ctrl-c"}.get(ch, ch)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def masked_input(prompt, mask="*"):
    """getpass와 달리 입력 길이를 mask 문자로 표시해 '입력되고 있음'을 눈으로 확인.
    비대화형(파이프 등)에서는 일반 input 으로 폴백."""
    if not sys.stdin.isatty():
        return input(prompt)
    sys.stdout.write(prompt)
    sys.stdout.flush()
    buf = []
    while True:
        try:
            k = _read_key()
        except KeyboardInterrupt:
            sys.stdout.write("\n")
            raise
        if k == "enter":
            sys.stdout.write("\n")
            break
        if k == "backspace":
            if buf:
                buf.pop()
                sys.stdout.write("\b \b")           # 화면에서 * 한 칸 지우기
                sys.stdout.flush()
            continue
        if k == "ctrl-c":
            sys.stdout.write("\n")
            raise KeyboardInterrupt
        if len(k) == 1 and k >= " ":                # 출력 가능한 문자만 마스킹
            buf.append(k)
            sys.stdout.write(mask)
            sys.stdout.flush()
    return "".join(buf)


def _select_menu(options, ansi):
    """↑/↓ 로 항목을 옮기고 Enter 로 선택하는 메뉴. 선택 문자열을 반환.
    ANSI 미지원·비대화형·목록이 화면보다 길면 None → 호출부가 번호 입력으로 폴백."""
    if not ansi or not sys.stdin.isatty() or not sys.stdout.isatty():
        return None
    if len(options) > shutil.get_terminal_size((80, 24)).lines - 3:
        return None                                 # 화면보다 길면 메뉴 대신 번호 입력
    idx = 0
    print("모델 선택 — ↑/↓ 이동, Enter 선택, q 직접입력")

    def render():
        for i, opt in enumerate(options):
            line = ("> " if i == idx else "  ") + opt
            if i == idx:
                line = "\033[7m" + line + "\033[0m"  # 반전(하이라이트)
            sys.stdout.write("\033[K" + line + "\n")  # \033[K: 줄 끝까지 지움
        sys.stdout.flush()

    render()
    while True:
        try:
            k = _read_key()
        except KeyboardInterrupt:
            return None
        if k == "up":
            idx = (idx - 1) % len(options)
        elif k == "down":
            idx = (idx + 1) % len(options)
        elif k == "enter":
            return options[idx]
        elif k in ("q", "Q", "esc", "ctrl-c"):
            return None
        else:
            continue
        sys.stdout.write("\033[%dA" % len(options))   # 커서를 목록 맨 위로 되돌림
        render()


def _choose_model(base, key, ansi):
    try:
        models = list_models(base, key)
    except Exception as e:
        print("모델 목록 실패: %s" % e)
        models = []
    if not models:
        return input("Model: ").strip()
    chosen = _select_menu(models, ansi)             # 방향키 메뉴 우선
    if chosen is not None:
        return chosen
    for i, m in enumerate(models, 1):               # 폴백: 번호/이름 입력
        print("  %2d) %s" % (i, m))
    sel = input("모델 번호 또는 이름: ").strip()
    if sel.isdigit() and 1 <= int(sel) <= len(models):
        return models[int(sel) - 1]
    return sel


HELP_TUI = ("명령:  /model 모델변경   /test 연결테스트   /clear 대화비우기   "
            "/help 도움말   /exit 종료   (응답 중 Ctrl+C 로 중지)")


def run_tui():
    color = _enable_ansi()

    def c(code, s):
        return ("\033[%sm%s\033[0m" % (code, s)) if color else s

    base = os.environ.get("LC_BASE_URL", "").strip()
    key = os.environ.get("LC_API_KEY", "").strip()
    model = os.environ.get("LC_MODEL", "").strip()
    system = os.environ.get("LC_SYSTEM", "").strip()
    temperature = None
    temp_env = os.environ.get("LC_TEMPERATURE", "").strip()
    if temp_env:
        try:
            temperature = float(temp_env)
        except ValueError:
            pass

    print(c("1;36", "Light Chat (TUI)"))
    if not base:
        base = input("Base URL [%s]: " % DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
    if not key:
        key = masked_input("API Key: ").strip()
    if not model:
        model = _choose_model(base, key, color)

    print(c("90", "모델: %s" % model))
    print(c("90", HELP_TUI))
    print(c("90", "-" * 56))

    history = []
    while True:
        try:
            user = input(c("1;32", "\n나> ")).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n종료되었습니다.")
            break
        if not user:
            continue
        if user in ("/exit", "/quit", "/q"):
            print("종료되었습니다.")
            break
        if user == "/help":
            print(c("90", HELP_TUI))
            continue
        if user == "/clear":
            history = []
            print(c("90", "대화를 지웠습니다."))
            continue
        if user == "/test":
            try:
                n = len(list_models(base, key))
                print(c("90", "✓ 연결 정상 (%d개 모델)" % n))
            except Exception as e:
                print(c("31", "✗ 연결 실패: %s" % e))
            continue
        if user == "/model":
            model = _choose_model(base, key, color)
            print(c("90", "모델: %s" % model))
            continue

        history.append({"role": "user", "content": user})
        msgs = ([{"role": "system", "content": system}] if system else []) + history

        sys.stdout.write(c("1;36", "AI> "))
        sys.stdout.flush()
        acc = []
        stats = {}
        t0 = time.perf_counter()
        first_at = None
        chunks = 0
        try:
            for delta in chat_stream(base, key, model, msgs, temperature, stats):
                if first_at is None:
                    first_at = time.perf_counter()
                chunks += 1
                sys.stdout.write(delta)
                sys.stdout.flush()
                acc.append(delta)
            print()
            metrics = _fmt_metrics(t0, first_at, time.perf_counter(), chunks, stats.get("usage"))
            if metrics:
                print(c("90", metrics))
            history.append({"role": "assistant", "content": "".join(acc)})
        except KeyboardInterrupt:
            print(c("90", "\n[중지됨]"))
            if acc:
                history.append({"role": "assistant", "content": "".join(acc)})
            else:
                history.pop()  # 빈 응답이면 직전 사용자 메시지 되돌림
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            print(c("31", "\n[HTTP %s] %s" % (e.code, detail)))
            history.pop()
        except Exception as e:
            print(c("31", "\n[오류] %s" % e))
            history.pop()


# ---------------------------------------------------------------------------
def main():
    configure_text_output()
    args = sys.argv[1:]
    if "-h" in args or "--help" in args:
        print(__doc__)
        return
    if "--tui" in args:
        run_tui()
        return
    port = next((int(a) for a in args if a.isdigit()), 8000)
    run_web(port)


if __name__ == "__main__":
    main()
