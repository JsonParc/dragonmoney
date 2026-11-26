# dragonmoney — 여러 AI가 토론해서 매매하는 미국 주식 봇

차트팀 AI 3명과 뉴스팀 AI 3명이 종목마다 토론하고, 과반이 동의한 행동만 실행합니다.
보유 종목 관련 뉴스는 여러 매체끼리 대조해서 확인된 뉴스에만 반응하고, 텔레그램과 휴대폰용 관리페이지로 보고·승인·제어합니다.

> ⚠️ 투자 손실 책임은 사용하는 사람에게 있습니다. 기본은 **모의투자**이고, 실전 연결(한국투자증권)은 아직 구현 전입니다.

## 내 PC에서 실행 (Windows)

1. Python 3.11+ 와 Node.js 20+ 설치
2. `.env.example` 을 복사해 `.env` 를 만들고 값을 채웁니다 (최소: `STOCKBOT_WEB_PASSWORD`, `STOCKBOT_PIN`, `STOCKBOT_SECRET_KEY`)
3. `start.bat` 실행 → 브라우저에서 http://127.0.0.1:8000
   - 키 없이 화면만 보기: `start.bat --demo` (비밀번호 `demo`)
   - 오늘·내일 스케줄 확인: `start.bat --dry-run`

## Render 배포

### 정적 사이트로 (무료, 지금 테스트용)
봇은 돌지 않고, **학습 파일을 읽기 전용으로 보여주는 화면**만 올라갑니다.
1. Render → **New → Static Site** → 이 저장소
2. Build Command: `cd web-ui && npm ci && npm run build` / Publish Directory: `web-ui/dist`
3. 기본으로 `web-ui/public/stockbot-state.json`(데모 데이터)을 보여줍니다. 내 PC에서 학습한 결과를 올리려면:
   `start.bat --export web-ui\public\stockbot-state.json` → 커밋·푸시 → 자동 재배포
   (화면의 **학습 파일 열기**로 올리지 않고 내 폰에서만 열어볼 수도 있습니다)
- 이 파일은 공개 주소로 누구나 볼 수 있습니다. 실제 계좌가 생기면 올리지 마세요.

### 동적 사이트로 (요금제 올렸을 때)
같은 코드가 서버를 감지하면 자동으로 실제 봇 화면(로그인·승인·설정·텔레그램)으로 동작합니다.

1. Render 대시보드 → **New → Blueprint** → 이 저장소 선택 (`render.yaml` 사용, Docker 웹 서비스)
2. 환경변수 입력: `STOCKBOT_WEB_PASSWORD`, `STOCKBOT_PIN`, 텔레그램 토큰·chat id, Finnhub·Gemini·Groq 키
3. 배포 후 `https://<서비스이름>.onrender.com` 접속

### 텔레그램 봇
SLBM 위키 밸런스 패치 봇과 **같은 봇 토큰**을 씁니다. 위키는 채널에 패치 소식을 보내고, 주식 봇은 개인 채팅에서 명령을 받습니다.
1. `STOCKBOT_TELEGRAM_TOKEN` 에 위키의 `BALANCE_TELEGRAM_BOT_TOKEN` 값을 넣고 배포
2. 텔레그램에서 그 봇과 1:1 대화를 열고 `/id` → 나온 숫자를 `STOCKBOT_TELEGRAM_CHAT_IDS` 에 `[숫자]` 로 넣고 재배포
3. 이후 `/status`, `/pending` 등 명령 사용 (명령어 메뉴는 시작할 때 자동 등록)
- 주식 봇이 켜져 있는 동안에는 위키 관리 화면의 "채널 ID 찾기"가 동작하지 않을 수 있습니다(같은 봇의 업데이트를 주식 봇이 받아가기 때문). 채널 ID는 이미 설정돼 있으면 문제없습니다.

### 무료 플랜 주의
- **15분 동안 접속이 없으면 서버가 잠듭니다.** 잠들면 스케줄러와 텔레그램도 멈춥니다. 외부 모니터링(예: UptimeRobot)으로 `/healthz` 를 5분마다 호출하면 깨어 있게 할 수 있습니다.
- **디스크가 유지되지 않습니다.** 재시작·재배포 때마다 DB(모의 계좌, 토론 기록, 점수판)가 초기화됩니다. 장기 운영은 영구 디스크가 있는 유료 플랜이나 외부 DB가 필요합니다.
- 메모리 512MB라 FinBERT(선택 기능)는 쓰지 않고 키워드 기반 뉴스 판정을 씁니다.

## 학습 파일 (내보내기 · 불러오기)
- 내보내기: `start.bat --export 파일.json` (LLM 응답 캐시까지: `--with-cache`) / 동적 사이트 설정 화면의 **내보내기**
- 불러오기: `start.bat --import 파일.json` / 동적 사이트 설정 화면의 **불러오기** (PIN 필요, 현재 기록을 덮어씀)
- 담기는 것: 설정, 좌석 점수·가중치, 토론 기록, 모의 계좌, 자산 추이. 키·PIN·비밀번호는 절대 담기지 않습니다.

## 개발

```
python -m venv .venv && .venv\Scripts\pip install -r requirements.lock && .venv\Scripts\pip install -e .[dev]
.venv\Scripts\python -m pytest -q
cd web-ui && npm install && npm run build
```

설계 문서: `docs/superpowers/specs/`, 구현 계획: `docs/superpowers/plans/`
