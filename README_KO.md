# Light Chat

*[English](README.md) · 한국어*

OpenAI 호환 API용 **단일 파일 채팅 클라이언트**. 웹 UI · 터미널(TUI) 두 가지 인터페이스가 `app.py` 하나에 들어 있으며, **외부 의존성이 전혀 없습니다(Python 표준 라이브러리만 사용).**

```
LightChatUI/
├── app.py        # 이 파일 하나가 전부 (UI 2종 + API 프록시 + 공유 코어)
├── README.md     # English
└── README_KO.md  # 한국어 (이 문서)
```

---

## 특징

- **단일 파일, 의존성 0** — `python app.py` 만으로 실행. `pip install` 불필요.
- **두 가지 UI 공존** — 웹 / TUI 가 같은 코어를 공유.
- **OpenAI 호환** — `/v1/chat/completions`, `/v1/models` 사용. OpenAI · Ollama · LM Studio · vLLM · LocalAI 등.
- **스트리밍** 응답 + 응답 중 **중지**.
- **모델 목록 자동 로드** + 편집 가능한 드롭다운/메뉴.
- **연결 테스트** — 모델 새로고침 버튼이 겸함.
- **TTFT / TPS 측정** — 각 응답마다 표시 (서버 usage 우선, 없으면 근사).
- **휘발성 우선** — 웹은 `sessionStorage`(탭 닫으면 소멸), TUI는 메모리 한정.
- **Cloudflare 등 게이트웨이 우회** — 프록시가 브라우저형 User-Agent 사용.

---

## 요구사항

- **Python 3.8+** (3.12에서 검증)
- 웹 · TUI 모드는 추가 요구사항 없음

---

## 실행

```bash
python app.py            # 웹 UI (기본 포트 8000) — 브라우저 자동 오픈
python app.py 8080       # 웹 UI, 포트 지정
python app.py --tui      # 터미널 채팅 (서버·프록시 불필요)
python app.py --help     # 사용법
```

---

## 설정 항목

| 항목 | 설명 | 예시 |
|---|---|---|
| **Base URL** | OpenAI 호환 엔드포인트 | `https://api.openai.com/v1`, `http://localhost:11434/v1` |
| **API Key** | 인증 키 (`Authorization: Bearer …`) | `sk-...` |
| **Model** | 모델 이름 (목록에서 선택 또는 직접 입력) | `gpt-4o-mini`, `llama3:8b` |
| **System** | (선택) 시스템 프롬프트 | |
| **Temperature** | (선택) 샘플링 온도 | `0.7` |

### 환경변수 (TUI 한정)

미리 지정하면 실행 시 입력을 건너뜁니다. (없으면 실행 중 입력받음)

```bash
LC_BASE_URL   LC_API_KEY   LC_MODEL   LC_SYSTEM   LC_TEMPERATURE
```

예 (PowerShell):

```powershell
$env:LC_BASE_URL="http://localhost:11434/v1"; $env:LC_API_KEY="dummy"; python app.py --tui
```

---

## 모드별 사용법

### 웹 UI (`python app.py`)
- 브라우저에서 자동으로 열림 (반드시 `http://localhost:PORT`, `file://` 아님).
- ⚙ 설정에서 항목 입력 → 모델 칸 ▾ 로 목록 펼침(전체 표시) 또는 직접 입력.
- ↻ 버튼: 모델 새로고침 **겸 연결 테스트** (`✓ 연결 정상` / `✗ 연결 실패`).
- 입력창: **Enter 전송 / Shift+Enter 줄바꿈**.
- 각 AI 응답 하단에 `TTFT … · … tok · … tok/s` 표시.

### 터미널 TUI (`python app.py --tui`)
- API Key는 입력 시 `*`로 **마스킹 표시**.
- 모델 선택은 **↑/↓ 방향키 메뉴**(Enter 선택, q 직접입력). 화면보다 길거나 비대화형이면 번호 입력으로 폴백.
- 명령:

  | 명령 | 동작 |
  |---|---|
  | `/model` | 모델 변경 |
  | `/test` | 연결 테스트 |
  | `/clear` | 대화 비우기 |
  | `/help` | 도움말 |
  | `/exit` | 종료 |
  | `Ctrl+C` | (응답 중) 중지 |

---

## TTFT / TPS 측정

| 지표 | 정의 | 정확도 |
|---|---|---|
| **TTFT** | 요청 전송 → 첫 토큰 도착까지 | 항상 정확 |
| **TPS** | 토큰수 ÷ (마지막 − 첫 토큰 시각) | 토큰 집계 방식에 의존 |

토큰 수는 요청 시 `stream_options.include_usage`로 **서버가 정확값(usage)을 주면 그것을 사용**하고, 주지 않으면 **수신 청크 수로 근사**하며 `~`를 붙입니다.

```
TTFT 0.50s · 120 tok · 60.0 tok/s     (정확)
TTFT 0.50s · ~80 tok · 40.0 tok/s     (근사)
```

---

## 데이터 수명주기 / 프라이버시

| 모드 | 저장 위치 | 재시작/재방문 후 |
|---|---|---|
| **웹** | 그 탭의 `sessionStorage` | **탭을 닫으면 URL·키·대화기록 모두 소멸**. 같은 탭 새로고침에는 유지 |
| **TUI** | 프로세스 메모리(또는 env) | 프로세스 종료 시 소멸 |

- 디스크에 평문으로 영속되는 데이터는 **없습니다**.
- API 키는 `Authorization` 헤더로 **설정한 업스트림에만** 전송되며, 요청 URL 경로에 실리지 않아 접근 로그에 남지 않습니다.
- 환경변수로 키를 지정하면 셸 환경·히스토리에 노출될 수 있으니 주의하세요.

---

## 아키텍처

```
app.py
├─ 공유 코어   open_upstream() · list_models() · chat_stream() · _fmt_metrics()
│              └ urllib + 브라우저형 User-Agent. 세 모드 공통.
├─ 웹 모드     run_web()   HTTP 서버 + 내장 HTML + /proxy
└─ TUI 모드    run_tui()   터미널 REPL (코어 직접 호출)
```

### 웹이 프록시를 두는 이유 (CORS · Cloudflare)
브라우저에서 외부 API를 직접 부르면 **CORS** 정책과, 일부 게이트웨이(예: Cloudflare)의 **봇 차단(403)** 에 막힙니다. 그래서 웹 모드는:

1. 브라우저는 **동일 출처**인 로컬 `/proxy` 로만 요청 → CORS·`origin=null` 문제 없음.
2. 파이썬 프록시가 업스트림으로 **서버 대 서버**로 전달 → CORS 무관.
3. 전달 시 **브라우저형 User-Agent** 를 붙여 Cloudflare 봇 차단 우회.

TUI는 브라우저가 아니므로 위 문제 자체가 없어 **프록시 없이 코어를 직접 호출**합니다.

---

## 동작하는 백엔드 예시

`Base URL` 만 바꾸면 그대로 동작합니다.

| 백엔드 | Base URL |
|---|---|
| OpenAI | `https://api.openai.com/v1` |
| Ollama | `http://localhost:11434/v1` |
| LM Studio | `http://localhost:1234/v1` |
| vLLM / LocalAI / 기타 호환 게이트웨이 | 각 서버 주소 + `/v1` |

---

## 트러블슈팅

- **모델 목록 실패 / 연결 실패 `HTTP 401`** — API Key가 틀렸습니다.
- **`HTTP 403`** — 게이트웨이(Cloudflare 등) 차단. 웹은 프록시가 UA로 우회하므로 거의 발생하지 않습니다.
- **웹에서 `file://`로 열면 동작 안 함** — 반드시 `python app.py` 실행 후 `http://localhost:PORT`로 접속하세요.
- **`stream_options` 오류로 요청 실패** — 드물게 이 옵션을 거부하는 서버가 있습니다. 그럴 경우 알려주시면 청크 근사만 쓰도록 되돌릴 수 있습니다.
