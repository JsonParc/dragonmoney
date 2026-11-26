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

1. Render 대시보드 → **New → Blueprint** → 이 저장소 선택 (`render.yaml` 사용)
2. 환경변수 입력: `STOCKBOT_WEB_PASSWORD`, `STOCKBOT_PIN`, 텔레그램 토큰·chat id, Finnhub·Gemini·Groq 키
3. 배포 후 `https://<서비스이름>.onrender.com` 접속

### 무료 플랜 주의
- **15분 동안 접속이 없으면 서버가 잠듭니다.** 잠들면 스케줄러와 텔레그램도 멈춥니다. 외부 모니터링(예: UptimeRobot)으로 `/healthz` 를 5분마다 호출하면 깨어 있게 할 수 있습니다.
- **디스크가 유지되지 않습니다.** 재시작·재배포 때마다 DB(모의 계좌, 토론 기록, 점수판)가 초기화됩니다. 장기 운영은 영구 디스크가 있는 유료 플랜이나 외부 DB가 필요합니다.
- 메모리 512MB라 FinBERT(선택 기능)는 쓰지 않고 키워드 기반 뉴스 판정을 씁니다.

## 개발

```
python -m venv .venv && .venv\Scripts\pip install -r requirements.lock && .venv\Scripts\pip install -e .[dev]
.venv\Scripts\python -m pytest -q
cd web-ui && npm install && npm run build
```

설계 문서: `docs/superpowers/specs/`, 구현 계획: `docs/superpowers/plans/`
