# Light Chat

*English · [한국어](README_KO.md)*

A **single-file chat client** for OpenAI-compatible APIs. Three interfaces — web UI, terminal (TUI), and a native GUI — all live in a single `app.py`, with **zero external dependencies (Python standard library only).**

```
LightChatUI/
├── app.py        # Everything is here (3 UIs + API proxy + shared core)
├── README.md     # English (this document)
└── README_KO.md  # Korean
```

---

## Features

- **Single file, zero dependencies** — run with just `python app.py`. No `pip install`.
- **Three coexisting UIs** — web / TUI / GUI share the same core.
- **OpenAI-compatible** — uses `/v1/chat/completions` and `/v1/models`. Works with OpenAI, Ollama, LM Studio, vLLM, LocalAI, etc.
- **Streaming** responses with the ability to **stop** mid-response.
- **Automatic model list loading** with an editable dropdown / menu.
- **Connection test** — handled by the model-refresh button.
- **TTFT / TPS metrics** — shown for every response (server-reported `usage` preferred, otherwise approximated).
- **Volatile by design** — the web UI uses `sessionStorage` (cleared when the tab closes); TUI/GUI keep data in memory only.
- **Bypasses gateways like Cloudflare** — the proxy sends a browser-style User-Agent.

---

## Requirements

- **Python 3.8+** (verified on 3.12)
- **tkinter is required only for GUI mode (`--gui`):**
  - Windows / macOS (python.org builds): bundled by default
  - Linux: may require `sudo apt install python3-tk` (or distro equivalent)
- Web and TUI modes have no extra requirements

---

## Running

```bash
python app.py            # Web UI (default port 8000) — opens the browser automatically
python app.py 8080       # Web UI on a specific port
python app.py --tui      # Terminal chat (no server / proxy needed)
python app.py --gui      # Native GUI window (tkinter, no server / proxy needed)
python app.py --help     # Usage
```

---

## Settings

| Field | Description | Example |
|---|---|---|
| **Base URL** | OpenAI-compatible endpoint | `https://api.openai.com/v1`, `http://localhost:11434/v1` |
| **API Key** | Auth key (`Authorization: Bearer …`) | `sk-...` |
| **Model** | Model name (pick from the list or type it) | `gpt-4o-mini`, `llama3:8b` |
| **System** | (optional) system prompt | |
| **Temperature** | (optional) sampling temperature | `0.7` |

### Environment variables (TUI / GUI only)

Set these in advance to skip the prompts at startup. (If unset, you'll be asked at runtime.)

```bash
LC_BASE_URL   LC_API_KEY   LC_MODEL   LC_SYSTEM   LC_TEMPERATURE
```

Example (PowerShell):

```powershell
$env:LC_BASE_URL="http://localhost:11434/v1"; $env:LC_API_KEY="dummy"; python app.py --tui
```

---

## Usage by mode

### Web UI (`python app.py`)
- Opens in the browser automatically (must be `http://localhost:PORT`, **not** `file://`).
- Enter values in ⚙ Settings → expand the model field with ▾ (shows all) or type directly.
- ↻ button: refreshes the model list **and doubles as a connection test** (`✓ Connected` / `✗ Failed`).
- Input box: **Enter to send / Shift+Enter for a newline**.
- Each AI response shows `TTFT … · … tok · … tok/s` underneath.

### Terminal TUI (`python app.py --tui`)
- The API Key is **masked with `*`** while typing.
- Model selection uses an **↑/↓ arrow-key menu** (Enter to select, q to type manually). Falls back to numbered input if the list is taller than the screen or the session is non-interactive.
- Commands:

  | Command | Action |
  |---|---|
  | `/model` | Change model |
  | `/test` | Connection test |
  | `/clear` | Clear conversation |
  | `/help` | Help |
  | `/exit` | Quit |
  | `Ctrl+C` | Stop (during a response) |

### Native GUI (`python app.py --gui`)
- Default tkinter theme (Windows = vista).
- "↻ Model/Connection" button: refreshes models and tests the connection.
- Enter to send / Shift+Enter for a newline; the send button toggles to "Stop" during a response.
- A metrics line is shown under each response.

---

## TTFT / TPS metrics

| Metric | Definition | Accuracy |
|---|---|---|
| **TTFT** | Request sent → first token received | Always accurate |
| **TPS** | tokens ÷ (last − first token time) | Depends on how tokens are counted |

The token count comes from `stream_options.include_usage`: if the **server returns an exact `usage` value, it is used**; otherwise the count is **approximated from the number of received chunks** and prefixed with `~`.

```
TTFT 0.50s · 120 tok · 60.0 tok/s     (exact)
TTFT 0.50s · ~80 tok · 40.0 tok/s     (approximate)
```

---

## Data lifecycle / privacy

| Mode | Storage | After restart / revisit |
|---|---|---|
| **Web** | the tab's `sessionStorage` | **URL, key, and history are all cleared when the tab closes**. Survives a same-tab reload |
| **TUI** | process memory (or env vars) | gone when the process exits |
| **GUI** | process memory (or env vars) | gone when the window closes |

- **No data is persisted to disk in plaintext.**
- The API key is sent via the `Authorization` header **only to the configured upstream**, and never appears in the request URL path, so it does not show up in access logs.
- Supplying the key via an environment variable may expose it to the shell environment / history — use with care.

---

## Architecture

```
app.py
├─ Shared core   open_upstream() · list_models() · chat_stream() · _fmt_metrics()
│                └ urllib + browser-style User-Agent. Common to all three modes.
├─ Web mode      run_web()   HTTP server + embedded HTML + /proxy
├─ TUI mode      run_tui()   terminal REPL (calls the core directly)
└─ GUI mode      run_gui()   tkinter (calls the core directly)
```

### Why the web UI has a proxy (CORS · Cloudflare)
Calling an external API directly from the browser runs into **CORS** policy and the **bot blocking (403)** of some gateways (e.g. Cloudflare). So the web mode:

1. The browser only talks to the **same-origin** local `/proxy` → no CORS / `origin=null` issues.
2. The Python proxy forwards to the upstream **server-to-server** → CORS does not apply.
3. It attaches a **browser-style User-Agent** when forwarding → bypasses Cloudflare bot blocking.

The TUI and GUI are not browsers, so these issues don't exist and they **call the core directly without a proxy**.

---

## Tested backends

Just change the `Base URL` and it works.

| Backend | Base URL |
|---|---|
| OpenAI | `https://api.openai.com/v1` |
| Ollama | `http://localhost:11434/v1` |
| LM Studio | `http://localhost:1234/v1` |
| vLLM / LocalAI / other compatible gateways | server address + `/v1` |

---

## Troubleshooting

- **Model list / connection fails with `HTTP 401`** — the API Key is wrong.
- **`HTTP 403`** — blocked by a gateway (e.g. Cloudflare). Rare on the web UI since the proxy works around it with the User-Agent.
- **Web UI doesn't work when opened via `file://`** — always run `python app.py` and connect to `http://localhost:PORT`.
- **Request fails due to `stream_options`** — a few servers reject this option. If that happens, let me know and it can be reverted to chunk-based approximation only.
- **tkinter error on `--gui` (Linux)** — install `sudo apt install python3-tk` and retry.
