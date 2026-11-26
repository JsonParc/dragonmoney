# Plan 1 — 핵심 봇 (PC에서 모의투자 하루 사이클) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사용자 PC에서 모의투자·반자동 모드로 "장마감 후 토론 → 보고서 → 승인 → 장시작 실행 → 뉴스 감시"가 돌아가고, 텔레그램과 웹 관리페이지로 보고·승인·제어할 수 있는 봇.

**Architecture:** 하나의 파이썬 프로세스(`python -m stockbot`)가 FastAPI 웹서버, APScheduler 스케줄러, 텔레그램 폴링을 함께 돌린다. 모든 상태는 SQLite 한 파일. 계산(지표·패턴·유동성·리스크)은 순수 함수로, LLM은 토론에만 쓰며 모든 외부 의존(시세·뉴스·LLM·브로커·텔레그램)은 Protocol 뒤에 숨겨 테스트에서 가짜로 바꾼다.

**Tech Stack:** Python 3.13, FastAPI, uvicorn, SQLAlchemy 2, pydantic 2 + pydantic-settings, APScheduler 3, exchange_calendars, pandas, yfinance, mplfinance, httpx, feedparser, openai SDK(OpenAI 호환 제공자 공용), anthropic SDK, python-telegram-bot 21, itsdangerous, pytest. 선택(extra `ml`): transformers + torch(CPU) for FinBERT. 프론트: React + Vite + TypeScript + Recharts.

**Spec:** `docs/superpowers/specs/2026-11-26-us-stock-debate-bot-design.md`

**이 계획의 범위:** 설계 문서 §7.1~7.12 중 PC 모의 운영에 필요한 부분. 이후 계획:
- **Plan 2 — 백테스트·튜닝·사례집**: 과거 뉴스 수집(Task 2 스파이크 결과 기반), 과거 S&P 500 구성종목, 익명화, 시뮬레이션 시계·응답 재생, 튜닝, 사건 사례집(§7.3), 비교 기준(§8.5), 백테스트 화면
- **Plan 3 — KIS·서버·무인 운영**: KIS 해외주식 어댑터(모의계좌 검증), 키 암호화 저장·휴대폰 실전 전환 흐름, Render 배포(Docker, render.yaml, 영구 디스크), DB 백업·주간 하트비트, Alembic 마이그레이션, 의존성 최종 고정, 한국어 README

## Global Constraints

- 저장소 루트: `c:\Users\박지민\Downloads\JsonParc_stock_bot`, 패키지 `src/stockbot/`, 테스트 `tests/`. Python 3.13.
- **시점 기준(as-of)**: 데이터 조회 함수는 모두 `as_of`(date 또는 datetime)를 받고 그 이후 데이터를 절대 반환하지 않는다.
- 시간대: 사용자 시각 `Asia/Seoul`(KST), 시장 시각 `America/New_York`, 휴장일·조기폐장은 `exchange_calendars`의 `XNYS`.
- **비밀값**: `.env`만 사용(`STOCKBOT_` 접두사), `.env`는 gitignore, `.env.example`만 커밋. 계좌·키·개인정보는 절대 LLM 프롬프트에 넣지 않는다(시장 데이터만).
- **무료 데이터만**: 시세·뉴스에 유료 소스 금지. LLM은 무료 티어 우선, 유료 호출은 월 상한 안에서만.
- 사용자에게 보이는 문구(텔레그램·웹·보고서)는 한국어.
- 설계 수치 기본값 (모두 런타임 설정으로 변경 가능):
  - 유동성: 20일 평균 거래대금 ≥ **$50,000,000**, 주문 수량 ≤ 20일 평균 거래량의 **1%**
  - 종목당 최대 비중 **20%**, 최대 보유 **8**종목, 강제 손절 **−15%**, 서킷브레이커 고점 대비 **−20%**
  - 모의 체결 슬리피지 **5bp**, 수수료 **0.25%** (KIS 온라인 해외주식 수준 — 내 판단)
  - 좌석 팀당 **3**석, 반박 라운드 최대 **2**회, 신규 후보 **5**개/일, 채점 기간 **5** 거래일
  - 점수: 개인 정답 **+1**/오답 **−1**, 설득+정답 **+2**, 설득+오답 **−2**, 교착 **−1**, 형식 위반 **−1**; 가중치 범위 **0.5~1.5**
  - LLM 월 상한 **$10**, 알림 **80%**
  - 뉴스 폴링 **10분**, 일일 보고서 **17:30 KST**
  - 자동 정지: 하루 주문 **10**건 또는 투입금의 **30%** 초과, 5거래일 내 같은 종목 **3**회 이상 왕복, 연속 손실 **5**회, 시세 0·15분 이상 지연·전일 대비 25% 이상 점프, 장부 불일치 (하루 한도·연속 손실·점프 수치는 내 판단)
- 의존성은 `pyproject.toml`에 선언하고 `requirements.lock`(`pip freeze --exclude-editable`)을 커밋, 의존성을 바꾸는 Task에서 갱신한다.
- 모든 Task는 `pytest -q`가 전부 통과한 상태로 커밋한다. 네트워크가 필요한 테스트는 `@pytest.mark.network`로 표시하고 기본 실행에서 제외한다.

## Review Focus

1. **휴장일·조기폐장·서머타임 전환일**: 장이 열리지 않는 날엔 토론·주문이 없어야 하고, 시각은 그날 실제 개장/폐장 기준으로 움직여야 한다 → Task 3 `test_holiday_and_early_close`, Task 19 `test_no_jobs_on_holiday`, `test_dst_shift`.
2. **LLM이 토론 도중 망가진 JSON을 주거나 429(속도 제한)를 던짐**: 그 좌석만 대체 모델로 넘어가거나 기권하고 토론은 결론까지 가야 한다 → Task 8 `test_router_falls_back_on_rate_limit`, Task 10 `test_invalid_seat_abstains`, `test_all_providers_down_yields_no_trade`.
3. **시세가 0이거나 오래됐거나 비정상적으로 튐**: 그 시세로는 주문이 나가지 않고 자동 정지가 걸려야 한다 → Task 12 `test_bad_quote_guards`, Task 13 `test_paper_broker_refuses_bad_quote`.
4. **실행 도중 프로세스 재시작**: 같은 결정으로 주문이 두 번 나가면 안 된다 → Task 13 `test_idempotent_order`, Task 14 `test_open_rerun_does_not_duplicate`.
5. **텔레그램에서 모르는 사람의 메시지, 이미 처리했거나 만료된 승인 버튼을 다시 누름**: 무시하거나 "이미 처리됨"으로 답해야 한다 → Task 16 `test_unknown_chat_ignored`, `test_double_approve`, `test_approve_after_expiry`.
6. **출처 하나뿐인 자극적 루머**: 확인되기 전엔 매도가 나가면 안 되고, 확인되면 그때 움직여야 한다 → Task 7b `test_single_low_tier_is_unconfirmed`, Task 14 `test_unconfirmed_rumor_only_notifies`.

---

### Task 1: 프로젝트 뼈대, 설정, DB

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`, `requirements.lock`, `src/stockbot/__init__.py`, `src/stockbot/config.py`, `src/stockbot/db.py`, `src/stockbot/models.py`, `src/stockbot/settings_store.py`, `tests/conftest.py`, `tests/test_config.py`

**Interfaces:**
- Produces:
  - `Settings(BaseSettings)` (env prefix `STOCKBOT_`): `db_url: str = "sqlite:///data/stockbot.db"`, `data_dir: Path = Path("data")`, `web_password: str`, `pin: str`, `secret_key: str`, `telegram_token: str | None`, `telegram_chat_ids: list[int] = []`, `finnhub_key`, `gemini_key`, `groq_key`, `openai_key`, `anthropic_key: str | None`; `get_settings() -> Settings`
  - `RiskConfig`, `DebateConfig`, `CostConfig`, `ModeState`, `SeatAssignment(seat_id: str, providers: list[str])`, `RuntimeConfig` (pydantic models, 기본값 = Global Constraints 수치). `ModeState`: `broker: Literal["paper","real"]="paper"`, `automation: Literal["semi","auto"]="semi"`, `paused: bool=False`, `pause_reason: str|None=None`. `RuntimeConfig` 추가 필드: `budget_usd: float = 10_000`, `rebuy_auto: bool = True`, `news_poll_minutes: int = 10`, `severity_threshold: int = 4`, `report_time_kst: str = "17:30"`
  - `DebateConfig` 추가 필드: `neutral_threshold: float = 0.005`, `hold_band: float = 0.02`, `weight_ema_alpha: float = 0.2`, `weight_k: float = 0.5`
  - `db.make_engine(url) -> Engine`, `db.make_session_factory(engine) -> sessionmaker`, `db.init_db(engine)` (create_all), `models.Base`
  - `settings_store.load_runtime(session) -> RuntimeConfig`, `settings_store.save_runtime(session, cfg: RuntimeConfig) -> None` (테이블 `runtime_settings(key PK, value JSON)`)
  - `tests/conftest.py` fixture `session_factory` (인메모리 SQLite), `runtime_cfg`

- [ ] **Step 1: `git init`, `.gitignore`(`.env`, `data/`, `.venv/`, `__pycache__/`, `web-ui/node_modules/`, `web-ui/dist/`), 가상환경 생성 `python -m venv .venv`, `pyproject.toml`(hatchling, src 레이아웃, extras `dev`=[pytest, httpx], `ml`=[transformers, torch]) 작성, `pip install -e .[dev]`**
- [ ] **Step 2: 실패하는 테스트 작성** — `tests/test_config.py`

```python
def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("STOCKBOT_WEB_PASSWORD", "pw"); monkeypatch.setenv("STOCKBOT_PIN", "1234")
    monkeypatch.setenv("STOCKBOT_SECRET_KEY", "s"); monkeypatch.setenv("STOCKBOT_TELEGRAM_CHAT_IDS", "[111,222]")
    s = Settings(_env_file=None)
    assert s.pin == "1234" and s.telegram_chat_ids == [111, 222]

def test_runtime_defaults():
    c = RuntimeConfig()
    assert c.risk.min_adv_usd == 50_000_000 and c.risk.max_adv_fraction == 0.01
    assert c.risk.max_position_pct == 0.20 and c.risk.max_holdings == 8
    assert c.risk.stop_loss_pct == -0.15 and c.risk.circuit_breaker_dd == -0.20
    assert c.debate.seats_per_team == 3 and c.debate.max_rebuttal_rounds == 2
    assert c.cost.monthly_cap_usd == 10.0 and c.mode.broker == "paper" and c.mode.automation == "semi"

def test_runtime_roundtrip(session_factory):
    with session_factory() as s:
        c = RuntimeConfig(); c.mode.automation = "auto"; save_runtime(s, c); s.commit()
    with session_factory() as s:
        assert load_runtime(s).mode.automation == "auto"

def test_env_file_is_gitignored():
    assert ".env" in Path(".gitignore").read_text().splitlines()
```

- [ ] **Step 3: `pytest -q` → 4개 FAIL(import error) 확인**
- [ ] **Step 4: `config.py`, `db.py`, `models.py`(Base + `RuntimeSetting`), `settings_store.py`, `.env.example`(모든 `STOCKBOT_*` 키를 빈 값으로) 구현**
- [ ] **Step 5: `pytest -q` → PASS, `pip freeze --exclude-editable > requirements.lock`**
- [ ] **Step 6: Commit** — `git add -A && git commit -m "chore: scaffold stockbot package, settings, db"`

---

### Task 2: 스파이크 — 무료 과거 뉴스 확보 방법, 무료 LLM 티어 실측 (버리는 코드)

TDD 아님. 결과는 문서 하나. 스크립트는 `scratch/`(gitignore에 추가)에 둔다.

**전제 (사용자 준비물):** Gemini API 키, Groq API 키, Finnhub 키를 `.env`에 입력. 없으면 해당 항목은 "미확인"으로 기록하고 진행.

- [ ] **Step 1: GDELT GKG 2.0 원본 파일 조사** — `http://data.gdeltproject.org/gdeltv2/masterfilelist.txt`에서 2024-03-01 하루치 GKG 파일 몇 개를 받아 (a) 파일 크기, (b) `V2Organizations`/`V2Themes`에 NVIDIA·Apple·Exxon 등이 잡히는 비율, (c) 제목/URL 추출 가능 여부를 확인. 2015~2025 전체를 받을 때와 "시간당 1개 파일만 표본" 받을 때의 총 용량·시간을 추정.
- [ ] **Step 2: 보조 소스 확인** — Finnhub `company-news`의 무료 조회 가능 과거 범위, GDELT 이벤트 테이블(지정학 사건)로 거시 사건을 잡을 수 있는지.
- [ ] **Step 3: 무료 LLM 티어 실측** — Gemini(OpenAI 호환 엔드포인트 `https://generativelanguage.googleapis.com/v1beta/openai/`)와 Groq(`https://api.groq.com/openai/v1`)에 Task 10 스타일 JSON 의견 요청을 각 20회 보내고 기록: 사용 가능한 무료 모델 ID, 분당/일일 한도(응답 헤더·문서), 평균 지연, JSON 형식 준수율, 이미지 입력 가능 모델.
- [ ] **Step 4: `docs/spikes/2026-11-27-news-and-llm.md` 작성** — 결론 3가지를 명시: ① Plan 2의 과거 뉴스 소스와 표본 방식 ② 좌석별 기본 모델 ID 표(무료 우선, 좌석 6개 + 심판 + 보고서) ③ 백테스트 2년치 1회 예상 소요 시간
- [ ] **Step 5: Commit** — `git commit -m "docs: spike results for news history and free LLM tiers"`

---

### Task 3: 장 달력과 시각 계산

**Files:**
- Create: `src/stockbot/market_calendar.py`, `tests/test_market_calendar.py`

**Interfaces:**
- Produces: `KST`, `NY` (ZoneInfo); `Session(date: date, open_kst: datetime, close_kst: datetime)`; `is_trading_day(d: date) -> bool`; `trading_session(d: date) -> Session` (휴장이면 `ValueError`); `next_trading_day(d: date) -> date`; `trading_days_between(start: date, end: date) -> int` (start 제외, end 포함); `is_market_open(now: datetime) -> bool`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
def test_winter_session():
    s = trading_session(date(2026, 12, 1))
    assert s.open_kst == datetime(2026, 12, 1, 23, 30, tzinfo=KST)
    assert s.close_kst == datetime(2026, 12, 2, 6, 0, tzinfo=KST)

def test_summer_session():
    s = trading_session(date(2026, 7, 1))
    assert s.open_kst == datetime(2026, 7, 1, 22, 30, tzinfo=KST)
    assert s.close_kst == datetime(2026, 7, 2, 5, 0, tzinfo=KST)

def test_holiday_and_early_close():
    assert not is_trading_day(date(2025, 12, 25))
    assert not is_trading_day(date(2026, 11, 26))          # Thanksgiving
    assert trading_session(date(2026, 11, 27)).close_kst == datetime(2026, 11, 28, 3, 0, tzinfo=KST)
    assert next_trading_day(date(2026, 12, 24)) == date(2026, 12, 28)

def test_trading_days_between():
    assert trading_days_between(date(2026, 12, 21), date(2026, 12, 28)) == 4   # 22,23,24,28

def test_is_market_open():
    assert is_market_open(datetime(2026, 12, 2, 0, 0, tzinfo=KST))
    assert not is_market_open(datetime(2026, 12, 2, 7, 0, tzinfo=KST))
```

- [ ] **Step 2: `pytest tests/test_market_calendar.py -q` → FAIL**
- [ ] **Step 3: `exchange_calendars.get_calendar("XNYS")`로 구현** (달력 객체는 모듈 수준에서 1회 생성)
- [ ] **Step 4: PASS 확인, lock 갱신**
- [ ] **Step 5: Commit** — `feat: market calendar with KST session times`

---

### Task 4: 가격 저장소와 종목 목록

**Files:**
- Create: `src/stockbot/data/__init__.py`, `src/stockbot/data/prices.py`, `src/stockbot/data/universe.py`, `data_static/sp500.csv`(ticker, name, sector — 현재 구성종목 스냅샷, 커밋), `tests/data/test_prices.py`
- Modify: `src/stockbot/models.py` (테이블 `bars(ticker, date, open, high, low, close, volume)` PK(ticker,date))

**Interfaces:**
- Produces:
  - `BarFetcher(Protocol)`: `fetch(ticker: str, start: date, end: date) -> pd.DataFrame` (columns open/high/low/close/volume, DatetimeIndex)
  - `YFinanceFetcher(BarFetcher)` (auto_adjust=True)
  - `PriceStore(session_factory, fetcher)`: `get_bars(ticker, as_of: date, lookback: int) -> pd.DataFrame` (마지막 행 ≤ as_of), `ensure(tickers: list[str], start: date, end: date) -> None`, `close_on(ticker, d: date) -> float` (d 이하 마지막 종가), `adv_usd(ticker, as_of, window=20) -> float`, `adv_shares(ticker, as_of, window=20) -> float`
  - `MACRO_TICKERS = {"oil": "CL=F", "us10y": "^TNX", "dxy": "DX-Y.NYB", "vix": "^VIX", "gold": "GC=F", "usdkrw": "KRW=X", "spy": "SPY", "qqq": "QQQ"}`, `SECTOR_ETFS: dict[str, str]` (GICS 11개 → XLK, XLE, …)
  - `load_universe() -> list[UniverseEntry(ticker, name, sector)]`

- [ ] **Step 1: 실패하는 테스트 작성** (가짜 fetcher가 2024-01-02~2024-01-31 영업일 바 반환, 호출 횟수 기록)

```python
def test_as_of_excludes_future(store):
    df = store.get_bars("AAPL", as_of=date(2024, 1, 10), lookback=5)
    assert df.index[-1].date() == date(2024, 1, 10) and len(df) == 5

def test_cache_hit_does_not_refetch(store, fake_fetcher):
    store.get_bars("AAPL", date(2024, 1, 10), 5); store.get_bars("AAPL", date(2024, 1, 9), 3)
    assert fake_fetcher.calls == 1

def test_adv_usd(store):   # fake: close=100, volume=600_000 every day
    assert store.adv_usd("AAPL", date(2024, 1, 31)) == pytest.approx(60_000_000)

def test_universe_has_sectors():
    u = load_universe(); assert len(u) >= 490 and all(e.sector for e in u)
```

- [ ] **Step 2: FAIL 확인**
- [ ] **Step 3: 구현** — 캐시 범위 밖 요청만 fetcher 호출, upsert 저장
- [ ] **Step 4: PASS, `@pytest.mark.network` 테스트 1개(`YFinanceFetcher`로 SPY 5일) 추가, lock 갱신**
- [ ] **Step 5: Commit** — `feat: price store with as-of reads and universe`

---

### Task 5: 차트 지표와 "차트쟁이" 패턴

**Files:**
- Create: `src/stockbot/signals/__init__.py`, `src/stockbot/signals/indicators.py`, `src/stockbot/signals/patterns.py`, `tests/signals/test_patterns.py`

**Interfaces:**
- Produces:
  - `compute_indicators(df: pd.DataFrame) -> pd.DataFrame` — 열 추가: `ma5, ma20, ma60, ma120, rsi14, macd, macd_signal, bb_upper, bb_lower, obv, vol_ratio20`
  - `ChartSignal(name: str, direction: Literal["bull","bear","neutral"], strength: float, text: str)` (pydantic)
  - `detect_patterns(ind: pd.DataFrame) -> list[ChartSignal]` — 마지막 행 기준. 이름 집합: `golden_cross_5_20`, `dead_cross_5_20`, `golden_cross_20_60`, `dead_cross_20_60`, `aligned_bull`(정배열), `aligned_bear`(역배열), `volume_spike`, `accumulation`(세력 매집), `long_bull_candle`, `long_bear_candle`, `upper_wick`, `lower_wick`, `pullback_to_ma20`(눌림목), `box_breakout`, `box_breakdown`, `rsi_overbought`, `rsi_oversold`
  - `text`는 한국어 한 줄 (예: `"거래량 20일 평균 대비 4.1배"`)
- 규칙 고정값: 장대봉 = 몸통 ≥ 직전 20일 평균 몸통의 2배; 꼬리 = 꼬리 ≥ 몸통의 2배; 박스 = 직전 20일 고저폭 ≤ 8%, 돌파 = 종가가 박스 상단 초과; 눌림목 = 정배열 상태에서 종가가 ma20의 ±2% 이내; `volume_spike` = vol_ratio20 ≥ 3; `accumulation` = 직전 20일 고저폭 ≤ 5% AND 20일 평균 거래량 ≥ 직전 60일 평균의 1.5배 AND OBV 20일 기울기 > 0

- [ ] **Step 1: 실패하는 테스트 작성** (합성 시계열 헬퍼 `make_df(closes, volumes)`)

```python
def test_golden_cross_only_on_cross_day():
    df = compute_indicators(make_df(closes=[100]*30 + [101, 103, 106, 110]))
    names_last = {s.name for s in detect_patterns(df)}
    names_prev = {s.name for s in detect_patterns(df.iloc[:-1])}
    assert ("golden_cross_5_20" in names_last) != ("golden_cross_5_20" in names_prev)

def test_volume_spike_text():
    df = compute_indicators(make_df(closes=[100]*40, volumes=[1_000]*39 + [4_100]))
    sig = next(s for s in detect_patterns(df) if s.name == "volume_spike")
    assert sig.strength == pytest.approx(4.1, rel=0.05) and "4.1배" in sig.text

def test_aligned_bull_on_steady_uptrend():
    df = compute_indicators(make_df(closes=[100 + i for i in range(150)]))
    assert "aligned_bull" in {s.name for s in detect_patterns(df)}
    assert df["rsi14"].iloc[-1] == pytest.approx(100)

def test_accumulation():
    closes = [100 + (i % 3) * 0.5 for i in range(100)]
    vols = [1_000]*80 + [2_000]*20
    df = compute_indicators(make_df(closes, vols))
    assert "accumulation" in {s.name for s in detect_patterns(df)}
```

- [ ] **Step 2: FAIL 확인**
- [ ] **Step 3: 구현** (pandas로 직접 계산, 외부 TA 라이브러리 불필요)
- [ ] **Step 4: PASS**
- [ ] **Step 5: Commit** — `feat: chart indicators and retail-style pattern signals`

---

### Task 6: 차트 이미지와 1차 필터(스크리너)

**Files:**
- Create: `src/stockbot/signals/chart_image.py`, `src/stockbot/signals/screener.py`, `tests/signals/test_screener.py`
- Consumes: Task 4 `PriceStore`, Task 5 `compute_indicators/detect_patterns`. **Task 12보다 먼저 실행되므로** 이 Task에서 `src/stockbot/risk/__init__.py`, `src/stockbot/risk/liquidity.py`, `src/stockbot/risk/portfolio.py`(아래 Task 12 Interfaces의 `PositionView`, `PortfolioView`, `MarketView` 정의)를 만들고 Task 12가 재사용한다.

**Interfaces:**
- Produces:
  - `render_chart_png(df: pd.DataFrame, path: Path, months: int = 6) -> Path` (mplfinance, 캔들+ma5/20/60/120+거래량, Agg 백엔드)
  - `risk/liquidity.py`: `liquidity_ok(adv_usd: float, adv_shares: float, qty: int, cfg: RiskConfig) -> tuple[bool, str]`; `affordable(price: float, budget_usd: float, cfg: RiskConfig) -> bool` (price ≤ budget × max_position_pct)
  - `Candidate(ticker: str, score: float, signals: list[ChartSignal], reason: str, held: bool)`
  - `HoldingFlag` 조건: 당일 |수익률| ≥ 3%, 또는 손절선까지 3%p 이내, 또는 관련 뉴스 심각도 ≥ 3, 또는 bear 신호 존재
  - `screen(as_of: date, universe: list[str], held: dict[str, PositionView], prices: PriceStore, news_severity: dict[str, int], budget_usd: float, cfg: RuntimeConfig) -> list[Candidate]` — 신호 있는 보유 종목 전부 + 신규 후보 상위 `cfg.debate.candidates_per_day`개 (유동성·가격 필터 통과만). 점수 = bull 신호 strength 합 − bear 신호 strength 합.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
def test_liquidity_threshold():
    cfg = RiskConfig()
    assert not liquidity_ok(49_000_000, 1e6, 10, cfg)[0]
    assert liquidity_ok(51_000_000, 1e6, 10, cfg)[0]
    assert not liquidity_ok(51_000_000, 1_000, 11, cfg)[0]       # 11 > 1% of 1,000

def test_affordable():
    assert affordable(1_999, 10_000, RiskConfig()) and not affordable(2_001, 10_000, RiskConfig())

def test_screen_limits_and_filters(fake_prices):   # 8개 종목: 1개 ADV 부족, 1개 주가 $5,000, 6개 bull 신호
    out = screen(date(2024, 6, 3), fake_prices.tickers, {}, fake_prices, {}, 10_000, RuntimeConfig())
    assert len(out) == 5 and "ILLIQ" not in {c.ticker for c in out} and "PRICEY" not in {c.ticker for c in out}
    assert [c.score for c in out] == sorted([c.score for c in out], reverse=True)

def test_screen_includes_flagged_holdings_only(fake_prices):
    held = {"CALM": pos(...), "DROP": pos(...)}   # DROP: 당일 -4%
    out = screen(date(2024, 6, 3), [], held, fake_prices, {}, 10_000, RuntimeConfig())
    assert {c.ticker for c in out} == {"DROP"} and out[0].held

def test_render_chart_png(tmp_path, fake_df):
    p = render_chart_png(fake_df, tmp_path / "c.png"); assert p.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
```

- [ ] **Step 2: FAIL 확인**
- [ ] **Step 3: 구현**
- [ ] **Step 4: PASS, lock 갱신**
- [ ] **Step 5: Commit** — `feat: screener, liquidity filter, chart image`

---

### Task 7: 뉴스 수집·저장·감성/심각도 판정

**Files:**
- Create: `src/stockbot/data/news.py`, `src/stockbot/sentiment/__init__.py`, `src/stockbot/sentiment/scorers.py`, `src/stockbot/sentiment/impact.py`, `tests/data/test_news.py`, `tests/sentiment/test_scorers.py`
- Modify: `models.py` (테이블 `news_items(id, url UNIQUE, title, summary, source, published_at, fetched_at, tickers JSON, tags JSON, sentiment REAL, severity INT)`)

**Interfaces:**
- Produces:
  - `NewsItem(url, title, summary, source, published_at: datetime, tickers: list[str], tags: list[str] = [], sentiment: float = 0.0, severity: int = 0)`
  - `NewsSource(Protocol)`: `fetch(since: datetime, tickers: list[str]) -> list[NewsItem]`; 구현 `RssSource(feeds: list[FeedSpec])`(feedparser, 제목의 회사명/티커로 tickers 매핑), `GoogleNewsSource()`(종목명·거시 키워드별 Google News RSS 검색, 원 출처 도메인 추출), `FinnhubSource(api_key)`(company-news + general news), `SecEdgarSource()`(보유 종목 8-K 공시 Atom 피드, User-Agent는 일반 클라이언트명)
  - `data_static/news_sources.yaml`: 피드 목록과 도메인별 신뢰 등급 0~3 (`FeedSpec(name, url, tier)`), `load_source_tiers() -> dict[str, int]` (모르는 도메인 = 3)
  - `NewsItem`에 필드 추가: `domain: str`, `wire: str | None` (AP/Reuters 등 통신사 표기 감지)
  - `NewsStore(session_factory)`: `add(items) -> int` (url 또는 정규화 제목 해시로 중복 제거, 새로 들어간 수 반환), `query(as_of: datetime, since: datetime, tickers: list[str] | None = None, min_severity: int = 0) -> list[NewsItem]`
  - `SentimentScorer(Protocol)`: `score(texts: list[str]) -> list[float]` (−1~1); 구현 `KeywordScorer`(기본), `FinBertScorer`(extra `ml` 설치 시, `ProsusAI/finbert`, CPU)
  - `impact.EVENT_TAGS`: 키워드 → 태그 (`geopolitical`, `oil_shock`, `rate_hike`, `rate_cut`, `inflation`, `pandemic`, `bank_crisis`, `tariff`, `regulation`, `supply_chain`, `earnings_miss`, `earnings_beat`, `lawsuit`)
  - `impact.TAG_SECTOR_IMPACT: dict[str, dict[str, int]]` (태그 → 섹터 → −2..+2; 예 `oil_shock`: Information Technology −1, Energy +2)
  - `impact.assess(item: NewsItem, sentiment: float) -> NewsItem` (tags·severity 0~5 채움), `impact.relevance(item, ticker, sector) -> int` (직접 언급 2, 섹터 영향 1, 무관 0)
  - `get_scorer() -> SentimentScorer` (FinBERT 가능하면 그것, 아니면 Keyword)

- [ ] **Step 1: 실패하는 테스트 작성**

```python
def test_query_respects_as_of(news_store):
    news_store.add([item(published_at=dt(2024,3,1,10)), item(url="u2", published_at=dt(2024,3,2,10))])
    assert len(news_store.query(as_of=dt(2024,3,1,23), since=dt(2024,2,1))) == 1

def test_dedupe(news_store):
    assert news_store.add([item(url="a"), item(url="a")]) == 1
    assert news_store.add([item(url="b", title="Same Title "), item(url="c", title="same title")]) == 1

def test_war_oil_headline():
    it = assess(item(title="Oil prices surge as war breaks out in Middle East"), sentiment=KeywordScorer().score(["Oil prices surge as war breaks out in Middle East"])[0])
    assert it.sentiment < 0 and {"geopolitical", "oil_shock"} <= set(it.tags) and it.severity >= 4
    assert relevance(it, "NVDA", "Information Technology") == 1

def test_neutral_headline_low_severity():
    it = assess(item(title="Company announces new office location"), 0.0)
    assert it.severity <= 1
```

- [ ] **Step 2: FAIL 확인**
- [ ] **Step 3: 구현** — FinBERT 테스트는 `pytest.importorskip("transformers")` + `@pytest.mark.slow`
- [ ] **Step 4: PASS, lock 갱신**
- [ ] **Step 5: Commit** — `feat: news ingestion, dedupe, sentiment and impact tagging`

---

### Task 7b: 뉴스 교차검증 (같은 사건 묶기, 독립 출처, 검증 상태)

**Files:**
- Create: `src/stockbot/data/verify.py`, `tests/data/test_verify.py`
- Modify: `models.py` (`news_items`에 `cluster_id INT`, `verification TEXT`, `independent_sources INT` 추가; 테이블 `news_clusters(id, first_seen, last_seen, headline, tickers JSON, tags JSON, verification, independent_sources, max_tier)`)

**Interfaces:**
- Consumes: Task 7 `NewsItem`, `NewsStore`, `load_source_tiers`
- Produces:
  - `Verification = Literal["confirmed","unconfirmed","contradicted"]`
  - `similar(a: NewsItem, b: NewsItem) -> float` — sentence-transformers 설치 시 임베딩 코사인, 아니면 불용어 제거 단어 Jaccard
  - `is_syndicated(a, b) -> bool` — 같은 `wire` 이거나 제목+요약 유사도 ≥ 0.95
  - `cluster(items: list[NewsItem], window_hours: int = 24, threshold: float = 0.6) -> list[list[NewsItem]]`
  - `independent_sources(group: list[NewsItem]) -> int` — 도메인 기준, 받아쓴 기사는 하나로
  - `verify(group: list[NewsItem], tiers: dict[str, int]) -> Verification` — 규칙: 0~1등급 반박 기사 존재 → `contradicted`; 0등급 ≥ 1 또는 1~2등급 독립 출처 ≥ 2 → `confirmed`; 그 외 `unconfirmed`. 반박 키워드: `denies, denied, false report, fake, rumor, hoax, not true, 부인, 사실무근, 루머, 가짜`
  - `NewsVerifier(session_factory, tiers)`: `update(as_of: datetime) -> list[ClusterRow]` (최근 window 안 기사를 재군집·재검증해 저장, 상태가 바뀐 묶음 반환), `cluster_of(news_id) -> ClusterRow`
  - `digest_line(cluster: ClusterRow) -> str` — 예: `"[확인됨·출처 5곳] Oil prices surge as war breaks out"`, 상태 문구 `확인됨/미확인/반박됨`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
TIERS = {"sec.gov": 0, "cnbc.com": 1, "marketwatch.com": 1, "smallblog.net": 3, "yahoo.com": 2}

def test_single_low_tier_is_unconfirmed():
    g = [item(domain="smallblog.net", title="Apple CEO to resign tomorrow")]
    assert verify(g, TIERS) == "unconfirmed"

def test_two_independent_reputable_confirm():
    g = [item(domain="cnbc.com", title="Oil jumps 10% after strike on refinery"), item(domain="marketwatch.com", title="Oil prices jump 10% after refinery strike")]
    assert verify(g, TIERS) == "confirmed" and independent_sources(g) == 2

def test_syndicated_copies_count_once():
    g = [item(domain="yahoo.com", wire="AP", title="X"), item(domain="cnbc.com", wire="AP", title="X")]
    assert independent_sources(g) == 1

def test_primary_source_confirms_alone():
    assert verify([item(domain="sec.gov", title="8-K: CEO departure")], TIERS) == "confirmed"

def test_denial_contradicts():
    g = [item(domain="smallblog.net", title="Nvidia to be banned from China"), item(domain="cnbc.com", title="Nvidia denies report of China ban")]
    assert verify(g, TIERS) == "contradicted"

def test_cluster_groups_same_event_only():
    items = [item(title="Oil jumps 10% after refinery strike", published_at=dt(2024,9,1,1)),
             item(title="Oil prices jump 10% after strike on refinery", published_at=dt(2024,9,1,3)),
             item(title="Apple unveils new iPhone", published_at=dt(2024,9,1,2))]
    assert sorted(len(g) for g in cluster(items)) == [1, 2]

def test_digest_line():
    assert digest_line(cluster_row("confirmed", 5, "Oil surges")).startswith("[확인됨·출처 5곳]")
```

- [ ] **Step 2: FAIL 확인**
- [ ] **Step 3: 구현**
- [ ] **Step 4: PASS**
- [ ] **Step 5: Commit** — `feat: cross-source news verification`

---

### Task 8: LLM 계층 (제공자, 캐시, 예산, 라우터)

**Files:**
- Create: `src/stockbot/llm/__init__.py`, `src/stockbot/llm/base.py`, `src/stockbot/llm/providers.py`, `src/stockbot/llm/cache.py`, `src/stockbot/llm/budget.py`, `src/stockbot/llm/router.py`, `src/stockbot/llm/pricing.py`, `tests/llm/test_router.py`, `tests/llm/fakes.py`
- Modify: `models.py` (테이블 `llm_calls(id, cache_key UNIQUE, provider, model, input_tokens, output_tokens, cost_usd, response_text, created_at)`)

**Interfaces:**
- Produces:
  - `LLMRequest(system: str, user: str, image_png: bytes | None = None, max_tokens: int = 800, temperature: float = 0.3, want_json: bool = True)`
  - `LLMResponse(text: str, provider: str, model: str, input_tokens: int, output_tokens: int, cost_usd: float, cached: bool = False)`
  - `LLMClient(Protocol)`: 속성 `provider: str`, `model: str`, `is_free: bool`, `supports_image: bool`; `complete(req: LLMRequest) -> LLMResponse`
  - 예외: `LLMError`, `RateLimited(LLMError)`, `AllProvidersFailed(LLMError)`
  - `OpenAICompatClient(provider, base_url, api_key, model, is_free, supports_image, price_in, price_out)` — openai SDK로 OpenAI·Groq·Gemini·OpenRouter 공용. HTTP 429 → `RateLimited`
  - `AnthropicClient(api_key, model, price_in, price_out)` — anthropic SDK (구현 시 `claude-api` 스킬 참고)
  - `pricing.MODEL_PRICES: dict[str, tuple[float, float]]` (USD/1M 토큰, 무료 모델 0) — 기본 모델 ID는 Task 2 스파이크 문서 표를 따른다
  - `CachedClient(inner: LLMClient, session_factory)` — 키 = sha256(provider|model|system|user|sha256(image)); 캐시 적중 시 `cached=True`, 비용 0
  - `BudgetTracker(session_factory, cfg: CostConfig)`: `month_spend(now: datetime) -> float`, `allow(client: LLMClient, now) -> bool`(무료는 항상 True, 유료는 spend < cap), `state(now) -> Literal["ok","alert","capped"]`, `record(resp: LLMResponse, now) -> None`
  - `LLMRouter(chains: dict[str, list[LLMClient]], budget: BudgetTracker)`: `complete(seat_id: str, req: LLMRequest, now: datetime) -> LLMResponse` — 체인 순서대로 시도, 예산 불허·`RateLimited`·`LLMError`면 다음, 이미지 요청인데 `supports_image=False`면 이미지 빼고 텍스트 지표만으로 요청, 전부 실패 시 `AllProvidersFailed`
  - `complete_json(router, seat_id, req, model_cls: type[BaseModel], now) -> tuple[BaseModel | None, LLMResponse | None]` — JSON 파싱(코드펜스 제거) + 검증, 실패 시 "JSON만 출력" 지시를 덧붙여 1회 재요청, 그래도 실패면 `(None, last_resp)`
  - `build_router(settings, runtime_cfg, session_factory) -> LLMRouter` — 키가 있는 제공자만 체인에 포함, 무료 → 유료 순
  - `tests/llm/fakes.py`: `ScriptedClient(responses: list[str | Exception], is_free=True, supports_image=True)` (호출 기록 `calls: list[LLMRequest]`)

- [ ] **Step 1: 실패하는 테스트 작성**

```python
def test_cache_hit(session_factory):
    inner = ScriptedClient(['{"a":1}']); c = CachedClient(inner, session_factory)
    r1 = c.complete(req()); r2 = c.complete(req())
    assert len(inner.calls) == 1 and r2.cached and r2.cost_usd == 0

def test_router_falls_back_on_rate_limit(budget):
    a = ScriptedClient([RateLimited()]); b = ScriptedClient(['{"x":1}'])
    r = LLMRouter({"s": [a, b]}, budget).complete("s", req(), NOW)
    assert r.text == '{"x":1}' and len(a.calls) == 1

def test_budget_blocks_paid_not_free(budget_at_cap):
    paid = ScriptedClient(['p'], is_free=False); free = ScriptedClient(['f'])
    assert LLMRouter({"s": [paid, free]}, budget_at_cap).complete("s", req(), NOW).text == "f"
    assert paid.calls == []

def test_budget_state(budget):   # cap 10
    budget.record(resp(cost=8.5), NOW); assert budget.state(NOW) == "alert"
    budget.record(resp(cost=2.0), NOW); assert budget.state(NOW) == "capped"
    assert budget.state(NOW.replace(month=NOW.month % 12 + 1)) == "ok"

def test_complete_json_retries_once():
    c = ScriptedClient(["not json", '```json\n{"v": 2}\n```']); r = LLMRouter({"s": [c]}, free_budget())
    obj, _ = complete_json(r, "s", req(), V, NOW); assert obj.v == 2 and len(c.calls) == 2

def test_image_dropped_for_text_only_model():
    c = ScriptedClient(['{}'], supports_image=False)
    LLMRouter({"s": [c]}, free_budget()).complete("s", req(image_png=b"png"), NOW)
    assert c.calls[0].image_png is None

def test_all_fail_raises():
    with pytest.raises(AllProvidersFailed):
        LLMRouter({"s": [ScriptedClient([LLMError()])]}, free_budget()).complete("s", req(), NOW)
```

- [ ] **Step 2: FAIL 확인**
- [ ] **Step 3: 구현**
- [ ] **Step 4: PASS, `@pytest.mark.network` 테스트(키가 있는 제공자에 짧은 JSON 요청) 추가, lock 갱신**
- [ ] **Step 5: Commit** — `feat: LLM providers with cache, monthly budget, fallback router`

---

### Task 9: 토론 스키마와 표결 계산 (순수 함수)

**Files:**
- Create: `src/stockbot/debate/__init__.py`, `src/stockbot/debate/schema.py`, `src/stockbot/debate/tally.py`, `tests/debate/test_tally.py`

**Interfaces:**
- Produces:
  - `Team(StrEnum)`: `CHART="chart"`, `NEWS="news"`
  - `Action(StrEnum)`: `BUY, ADD, HOLD, TRIM, SELL, SELL_REBUY, SWITCH`
  - `Direction(StrEnum)`: `BUY_SIDE="buy_side"`, `HOLD="hold"`, `SELL_SIDE="sell_side"`; `DIRECTION_OF: dict[Action, Direction]` (BUY/ADD→BUY_SIDE, HOLD→HOLD, TRIM/SELL/SELL_REBUY/SWITCH→SELL_SIDE)
  - `OpinionBody(BaseModel)` — LLM이 내는 JSON: `action: Action`, `confidence: float (0~1)`, `size_pct: float | None` (매수: 투입금 대비 비중, TRIM: 보유 대비 매도 비율), `target_price: float | None`, `rebuy_price: float | None`, `expected_drop_pct: float | None`, `horizon_days: int = 5`, `switch_to: str | None`, `rationale: str`, `evidence: list[str] = []`
  - `Opinion(OpinionBody)` + `seat_id: str`, `team: Team`, `round: int`, `valid: bool = True`
  - `ResolvedAction(action: Action, size_pct: float | None, target_price: float | None, rebuy_price: float | None, switch_to: str | None)`
  - `PersuasionRecord(persuading_team: Team | None, switched_seats: list[str])`
  - `team_position(opinions: list[Opinion], weights: dict[str, float], team: Team) -> Direction | None` (유효 의견 가중 다수, 동률 None)
  - `direction_vote(opinions, weights) -> tuple[Direction | None, dict[Direction, float]]` (유효 의견 가중치 합 대비 점유율, **> 0.5**인 방향만 승리)
  - `resolve_details(opinions, weights, direction: Direction) -> ResolvedAction` (방향 내 최대 가중 행동; 그 행동을 제안한 의견들의 수치 필드 가중 중앙값; `switch_to`는 최다 가중 값)
  - `detect_persuasion(round0: list[Opinion], final: list[Opinion], final_direction: Direction | None) -> PersuasionRecord` (round0에서 final_direction이 아니었고 final에서 final_direction인 좌석 = switched; 그 좌석이 있고, final_direction이 한 팀의 round0 team_position과 같고 다른 팀과는 다르면 그 팀이 persuading_team)

- [ ] **Step 1: 실패하는 테스트 작성** (`op(seat, team, action, **kw)` 헬퍼, 좌석 c1~c3 차트, n1~n3 뉴스)

```python
W1 = {s: 1.0 for s in ["c1","c2","c3","n1","n2","n3"]}

def test_split_three_ways_no_winner():
    ops = [op("c1",C,"BUY"), op("c2",C,"BUY"), op("c3",C,"HOLD"), op("n1",N,"SELL"), op("n2",N,"SELL"), op("n3",N,"HOLD")]
    assert team_position(ops, W1, C) == Direction.BUY_SIDE and team_position(ops, W1, N) == Direction.SELL_SIDE
    d, shares = direction_vote(ops, W1); assert d is None and shares[Direction.HOLD] == pytest.approx(1/3)

def test_exact_half_is_deadlock():
    ops = [op(s, C, "BUY") for s in ["c1","c2","c3"]] + [op(s, N, "SELL") for s in ["n1","n2","n3"]]
    assert direction_vote(ops, W1)[0] is None

def test_weights_break_balance():
    w = {**{s: 1.5 for s in ["c1","c2","c3"]}, **{s: 0.5 for s in ["n1","n2","n3"]}}
    ops = [op(s, C, "BUY") for s in ["c1","c2","c3"]] + [op(s, N, "SELL") for s in ["n1","n2","n3"]]
    d, shares = direction_vote(ops, w); assert d == Direction.BUY_SIDE and shares[d] == pytest.approx(0.75)

def test_invalid_excluded_from_denominator():
    ops = [op("c1",C,"SELL"), op("c2",C,"SELL"), op("c3",C,"HOLD", valid=False), op("n1",N,"SELL"), op("n2",N,"HOLD"), op("n3",N,"HOLD", valid=False)]
    assert direction_vote(ops, W1)[0] == Direction.SELL_SIDE        # 3/4

def test_resolve_details_weighted_median():
    ops = [op("c1",C,"TRIM", size_pct=0.5), op("n1",N,"SELL_REBUY", rebuy_price=90), op("n2",N,"SELL_REBUY", rebuy_price=94), op("n3",N,"SELL_REBUY", rebuy_price=100)]
    r = resolve_details(ops, W1, Direction.SELL_SIDE); assert r.action == Action.SELL_REBUY and r.rebuy_price == 94

def test_persuasion_detected():
    r0 = [op(s, C, "BUY") for s in ["c1","c2","c3"]] + [op("n1",N,"SELL"), op("n2",N,"SELL"), op("n3",N,"SELL")]
    fin = [op(s, C, "BUY") for s in ["c1","c2","c3"]] + [op("n1",N,"BUY"), op("n2",N,"SELL"), op("n3",N,"SELL")]
    p = detect_persuasion(r0, fin, Direction.BUY_SIDE)
    assert p.persuading_team == Team.CHART and p.switched_seats == ["n1"]
```

- [ ] **Step 2: FAIL 확인**
- [ ] **Step 3: 구현**
- [ ] **Step 4: PASS**
- [ ] **Step 5: Commit** — `feat: debate schema and weighted tally`

---

### Task 10: 토론 엔진 (좌석, 프롬프트, 라운드 진행, 심판)

**Files:**
- Create: `src/stockbot/debate/seats.py`, `src/stockbot/debate/prompts.py`, `src/stockbot/debate/engine.py`, `tests/debate/test_engine.py`
- Modify: `models.py` (테이블 `debates(id, ticker, as_of, kind, direction, deadlock, persuading_team, referee_summary, result_json, created_at)`, `opinions(id, debate_id, seat_id, team, round, valid, body_json)`)

**Interfaces:**
- Consumes: Task 8 `LLMRouter`, `complete_json`, `AllProvidersFailed`; Task 9 전부
- Produces:
  - `Seat(seat_id: str, team: Team, role_ko: str, persona: str, uses_image: bool)` (frozen dataclass); `DEFAULT_SEATS`: `chart_trend`(이평·추세), `chart_volume`(거래량·세력), `chart_candle`(캔들·패턴) — `uses_image=True`; `news_news`(뉴스), `news_case`(사례참고), `news_macro`(거시경제); `REFEREE_ID = "referee"`
  - `DebateContext(ticker, sector, as_of: date, kind: Literal["regular","emergency"], holding: PositionView | None, last_price: float, chart_signals: list[str], indicator_summary: dict[str, float], chart_png: bytes | None, news_digest: list[str], macro_digest: list[str], case_digest: str | None = None, scoreboard_text: str = "", anonymize: bool = False)`
  - `DebateResult(ticker, as_of, kind, rounds: list[list[Opinion]], direction: Direction | None, shares: dict[Direction, float], resolved: ResolvedAction | None, deadlock: bool, persuasion: PersuasionRecord, invalid_seats: list[str], referee_summary: str)`
  - `prompts.seat_prompt(seat, ctx, round: int, prior: list[Opinion]) -> LLMRequest` — 차트팀은 차트 신호·지표·이미지만(뉴스 없음), 뉴스팀은 뉴스·거시·사례만(차트 이미지 없음); round ≥ 1이면 이전 라운드 전원 의견(좌석·팀·행동·근거) 포함; 모든 프롬프트에 점수판 텍스트와 "반드시 하나의 행동을 고를 것, 모르겠다 불가" 규칙, `OpinionBody` JSON 스키마 포함; `anonymize=True`면 티커→`"종목 A"`, 날짜→`"D일"` 치환
  - `DebateEngine(seats: list[Seat], router: LLMRouter, cfg: DebateConfig, now_fn: Callable[[], datetime])`: `run(ctx: DebateContext, weights: dict[str, float], max_rounds: int | None = None) -> DebateResult`
  - 흐름: round 0 전원 → 팀 입장이 같으면 종료 → 아니면 반박 라운드(최대 `max_rounds or cfg.max_rebuttal_rounds`), 매 라운드 후 `direction_vote`가 승자를 내면 종료 → 끝까지 승자 없으면 `deadlock=True` → 심판 요약 1회(실패해도 `""`)
  - 좌석 실패(`complete_json`이 None 또는 `AllProvidersFailed`): 그 라운드 `valid=False`인 HOLD 의견으로 기록 + `invalid_seats`에 추가
  - `save_result(session, result) -> int` (debates/opinions 저장, debate_id 반환)

- [ ] **Step 1: 실패하는 테스트 작성** (`scripted_router({seat_id: [json...]})` 헬퍼)

```python
def test_agreement_ends_after_round0():
    r = scripted_router({s: [body("BUY")] for s in SEAT_IDS}, referee=["요약"])
    res = engine(r).run(ctx(), W1)
    assert len(res.rounds) == 1 and res.direction == Direction.BUY_SIDE and r.calls_for("chart_trend") == 1

def test_persuasion_in_rebuttal():
    script = {**{c: [body("BUY"), body("BUY")] for c in CHART}, "news_news": [body("SELL"), body("BUY")],
              "news_case": [body("SELL"), body("SELL")], "news_macro": [body("SELL"), body("SELL")]}
    res = engine(scripted_router(script)).run(ctx(), W1)
    assert res.direction == Direction.BUY_SIDE and res.persuasion.persuading_team == Team.CHART

def test_deadlock_after_max_rounds():
    script = {**{c: [body("BUY")]*3 for c in CHART}, **{n: [body("SELL")]*3 for n in NEWS}}
    res = engine(scripted_router(script)).run(ctx(), W1)
    assert res.deadlock and res.direction is None and len(res.rounds) == 3

def test_invalid_seat_abstains():
    script = {**{s: [body("SELL")] for s in SEAT_IDS}, "chart_trend": ["garbage", "still garbage"]}
    res = engine(scripted_router(script)).run(ctx(), W1)
    assert "chart_trend" in res.invalid_seats and res.direction == Direction.SELL_SIDE

def test_all_providers_down_yields_no_trade():
    res = engine(scripted_router({s: [LLMError()]*6 for s in SEAT_IDS})).run(ctx(), W1)
    assert res.direction is None and set(res.invalid_seats) == set(SEAT_IDS)

def test_team_inputs_are_separated():
    req_c = seat_prompt(SEATS["chart_trend"], ctx(news_digest=["WAR NEWS"]), 0, [])
    req_n = seat_prompt(SEATS["news_news"], ctx(chart_png=b"png"), 0, [])
    assert "WAR NEWS" not in req_c.user and req_n.image_png is None

def test_anonymize():
    req = seat_prompt(SEATS["news_news"], ctx(ticker="NVDA", as_of=date(2024,8,5), news_digest=["NVDA falls on 2024-08-05"], anonymize=True), 0, [])
    assert "NVDA" not in req.user and "2024-08-05" not in req.user
```

- [ ] **Step 2: FAIL 확인**
- [ ] **Step 3: 구현** — 좌석 역할 프롬프트는 TradingAgents(TauricResearch)의 분석가/토론 프롬프트 구성을 참고해 한국어로 작성. 같은 라운드 좌석 호출은 `concurrent.futures.ThreadPoolExecutor`로 병렬
- [ ] **Step 4: PASS**
- [ ] **Step 5: Commit** — `feat: debate engine with rebuttal rounds and referee`

---

### Task 11: 점수판과 가중치 (결과 검증형 보너스)

**Files:**
- Create: `src/stockbot/scoring/__init__.py`, `src/stockbot/scoring/scoreboard.py`, `tests/scoring/test_scoreboard.py`
- Modify: `models.py` (테이블 `decisions(id, debate_id, ticker, as_of, direction, ref_price, graded, outcome, ret)`, `seat_scores(seat_id PK, ema REAL, weight REAL, n INT)`, `score_events(id, seat_id, debate_id, delta, reason, created_at)`)

**Interfaces:**
- Consumes: Task 3 `trading_days_between`, Task 9/10 `DebateResult`, `Direction`, `Team`
- Produces:
  - `grade(direction: Direction, ret: float, cfg: DebateConfig) -> Literal["correct","wrong","neutral"]` — BUY_SIDE: ret > neutral → correct, ret < −neutral → wrong; SELL_SIDE 반대; HOLD: |ret| ≤ hold_band → correct, 아니면 wrong; 그 외 neutral
  - `update_weight(ema: float, delta: float, cfg) -> tuple[float, float]` — `ema' = (1−α)·ema + α·delta`, `weight = clamp(1 + k·ema', weight_min, weight_max)`
  - `Scoreboard(session_factory, cfg: DebateConfig, seat_ids: list[str])`:
    - `weights() -> dict[str, float]` (기록 없으면 1.0)
    - `record_debate(debate_id: int, result: DebateResult, ref_price: float) -> int | None` — 즉시 점수: 교착이면 전원 −deadlock_penalty, invalid 좌석 −invalid_penalty; direction이 있으면 `decisions` 행 생성 후 id 반환
    - `grade_due(as_of: date, close_on: Callable[[str, date], float]) -> list[int]` — `trading_days_between(decision.as_of, as_of) >= grading_horizon_days`인 미채점 결정 채점: 각 유효 좌석의 최종 라운드 방향으로 개인 ±1; 결정 결과가 correct면 persuading_team 전원 +bonus, wrong이면 −persuasion_penalty; 채점된 decision id 목록 반환
    - `summary_text() -> str` (한국어 점수판: 좌석, 가중치, 최근 20건 적중률)

- [ ] **Step 1: 실패하는 테스트 작성**

```python
def test_grade():
    cfg = DebateConfig()
    assert grade(Direction.BUY_SIDE, 0.01, cfg) == "correct" and grade(Direction.BUY_SIDE, -0.01, cfg) == "wrong"
    assert grade(Direction.SELL_SIDE, 0.003, cfg) == "neutral" and grade(Direction.HOLD, 0.03, cfg) == "wrong"

def test_update_weight_and_clamp():
    ema, w = update_weight(0.0, 3.0, DebateConfig()); assert ema == pytest.approx(0.6) and w == pytest.approx(1.3)
    for _ in range(20): ema, w = update_weight(ema, 3.0, DebateConfig())
    assert w == 1.5
    for _ in range(40): ema, w = update_weight(ema, -3.0, DebateConfig())
    assert w == 0.5

def test_persuasion_bonus_only_when_correct(board):
    did = board.record_debate(1, persuaded_result(direction=Direction.BUY_SIDE, team=Team.CHART), ref_price=100)
    graded = board.grade_due(date(2024, 6, 10), close_on=lambda t, d: 103.0)   # 5 trading days later, +3%
    assert graded == [did]
    events = board_events(board, "chart_trend"); assert {e.delta for e in events} >= {1.0, 2.0}

def test_persuasion_penalty_when_wrong(board):
    board.record_debate(1, persuaded_result(Direction.BUY_SIDE, Team.CHART), 100)
    board.grade_due(date(2024, 6, 10), close_on=lambda t, d: 97.0)
    assert -2.0 in {e.delta for e in board_events(board, "chart_trend")}

def test_not_graded_before_horizon(board):
    board.record_debate(1, persuaded_result(Direction.BUY_SIDE, Team.CHART), 100)
    assert board.grade_due(date(2024, 6, 7), close_on=lambda t, d: 103.0) == []

def test_deadlock_penalizes_everyone(board):
    assert board.record_debate(2, deadlock_result(), 100) is None
    assert all(board.weights()[s] < 1.0 for s in SEAT_IDS)
```
(헬퍼의 결정일은 2024-06-03 월요일)

- [ ] **Step 2: FAIL 확인**
- [ ] **Step 3: 구현**
- [ ] **Step 4: PASS**
- [ ] **Step 5: Commit** — `feat: outcome-verified scoreboard and seat weights`

---

### Task 12: 리스크 규칙과 자동 정지 조건

**Files:**
- Create: `src/stockbot/risk/rules.py`, `src/stockbot/risk/guards.py`, `tests/risk/test_rules.py`, `tests/risk/test_guards.py`
- Consumes: Task 6 `risk/liquidity.py`, `risk/portfolio.py`; Task 9/10 `DebateResult`, `Action`, `Direction`

**Interfaces:**
- Produces:
  - `portfolio.py` (Task 6에서 생성됨): `PositionView(ticker, qty: int, avg_price: float, last_price: float)`, `PortfolioView(cash: float, positions: dict[str, PositionView], peak_equity: float)` + property `equity`; `MarketView(Protocol)`: `last_price(t) -> float`, `adv_usd(t) -> float`, `adv_shares(t) -> float`
  - `OrderKind = Literal["new_buy","add","rebuy","trim","sell","stop_loss","switch_sell","switch_buy"]`
  - `OrderIntent(ticker, side: Literal["buy","sell"], qty: int, kind: OrderKind, limit_price: float | None = None, expires_at: datetime | None = None, decision_id: int | None = None, reason: str, idempotency_key: str)` — key = f"{decision_id}:{kind}:{ticker}" (손절은 f"stop:{ticker}:{as_of}")
  - `decision_to_intents(result: DebateResult, decision_id: int, pf: PortfolioView, mkt: MarketView, budget_usd: float, cfg: RiskConfig, as_of: date) -> list[OrderIntent]`:
    - BUY/ADD: 금액 = min(size_pct or 0.1, max_position_pct) × budget − 기존 보유 평가액, qty = floor(금액 / last_price)
    - TRIM: qty = floor(보유 × (size_pct or 0.5)); SELL: 전량
    - SELL_REBUY: 전량 매도 + `rebuy` 지정가 매수(limit=rebuy_price, qty=매도 수량, expires_at = 20거래일 후 장마감 — 내 판단)
    - SWITCH: 전량 `switch_sell` + `switch_to`에 대한 `switch_buy`(BUY와 같은 금액 규칙)
    - HOLD/None → `[]`
  - `RiskOutcome(accepted: list[OrderIntent], rejected: list[tuple[OrderIntent, str]])`
  - `apply_risk(intents, pf, mkt, budget_usd, cfg: RiskConfig, mode: ModeState, circuit_tripped: bool) -> RiskOutcome` — 매수 쪽 거절 사유: 유동성, 1주 가격 초과(affordable), 보유 종목 수 한도(신규만), 투입금 초과(보유 평가액+주문액 > budget), 현금 부족, `mode.paused`, `circuit_tripped`. 매도 쪽은 보유 수량 초과만 거절.
  - `forced_stop_losses(pf, cfg, as_of: date) -> list[OrderIntent]` (손익률 ≤ stop_loss_pct)
  - `circuit_breaker_tripped(pf, cfg) -> bool` (equity / peak − 1 ≤ circuit_breaker_dd)
  - `guards.py`: `GuardTrip(code: Literal["DAILY_ORDER_LIMIT","CHURN","CONSECUTIVE_LOSSES","BAD_QUOTE","DATA_STALE","LEDGER_MISMATCH"], message: str)`;
    `check_quote(price: float, quote_time: datetime, now: datetime, prev_close: float) -> GuardTrip | None` (price ≤ 0 or |price/prev_close − 1| > 0.25 → BAD_QUOTE; 장중 now − quote_time > 15분 → DATA_STALE);
    `check_daily_limits(today_orders: list[OrderIntent], prices: dict[str, float], budget_usd: float, cfg) -> GuardTrip | None` (건수 > 10 또는 금액 > 30%);
    `check_churn(fills: list[FillRecord], as_of: date, cfg) -> GuardTrip | None` (같은 종목 매수→매도 왕복이 `churn_window_days` 거래일 안에 `churn_round_trips`회 이상);
    `check_consecutive_losses(closed_trade_pnls: list[float], cfg) -> GuardTrip | None`;
    `check_ledger(book: dict[str, int], broker: dict[str, int]) -> GuardTrip | None`
  - `FillRecord(ticker, side, qty, price, filled_at: datetime)`
  - `RiskConfig`에 추가: `max_orders_per_day=10`, `max_daily_notional_pct=0.30`, `churn_round_trips=3`, `churn_window_days=5`, `max_consecutive_losses=5`, `quote_stale_minutes=15`, `quote_jump_pct=0.25`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
def test_buy_sizing_clipped():
    ints = decision_to_intents(res(Action.BUY, size_pct=0.3), 7, empty_pf(cash=10_000), mkt(price=150), 10_000, RiskConfig(), D)
    assert ints[0].qty == 13 and ints[0].kind == "new_buy" and ints[0].idempotency_key == "7:new_buy:T"

def test_sell_rebuy_creates_two_orders():
    ints = decision_to_intents(res(Action.SELL_REBUY, rebuy_price=90), 8, pf_with("T", qty=10, avg=100, last=98), mkt(98), 10_000, RiskConfig(), D)
    assert [(i.side, i.kind, i.qty) for i in ints] == [("sell","sell",10), ("buy","rebuy",10)] and ints[1].limit_price == 90

def test_liquidity_and_holdings_rejections():
    out = apply_risk([buy("ILLIQ", 5)], empty_pf(10_000), mkt(adv_usd={"ILLIQ": 49e6}), 10_000, RiskConfig(), ModeState(), False)
    assert out.accepted == [] and "유동성" in out.rejected[0][1]
    out = apply_risk([buy("NEW", 1)], pf_with_n_holdings(8), mkt(), 10_000, RiskConfig(), ModeState(), False)
    assert out.accepted == []

def test_paused_blocks_buys_not_sells():
    out = apply_risk([buy("A", 1), sell("B", 1)], pf_with("B", 1, 100, 100), mkt(), 10_000, RiskConfig(), ModeState(paused=True), False)
    assert [i.side for i in out.accepted] == ["sell"]

def test_forced_stop_loss_boundary():
    assert forced_stop_losses(pf_with("T", 10, 100, 84.9), RiskConfig(), D)[0].kind == "stop_loss"
    assert forced_stop_losses(pf_with("T", 10, 100, 85.1), RiskConfig(), D) == []

def test_circuit_breaker():
    assert circuit_breaker_tripped(PortfolioView(cash=7_999, positions={}, peak_equity=10_000), RiskConfig())
    assert not circuit_breaker_tripped(PortfolioView(cash=8_001, positions={}, peak_equity=10_000), RiskConfig())

def test_bad_quote_guards():
    assert check_quote(0, NOW, NOW, 100).code == "BAD_QUOTE"
    assert check_quote(130, NOW, NOW, 100).code == "BAD_QUOTE"
    assert check_quote(101, NOW - timedelta(minutes=20), NOW_MARKET_OPEN, 100).code == "DATA_STALE"
    assert check_quote(101, NOW, NOW, 100) is None

def test_churn_and_limits():
    fills = round_trips("T", n=3, within_days=4)
    assert check_churn(fills, D, RiskConfig()).code == "CHURN"
    assert check_daily_limits([buy(f"T{i}", 1) for i in range(11)], {}, 10_000, RiskConfig()).code == "DAILY_ORDER_LIMIT"
    assert check_consecutive_losses([-1]*5, RiskConfig()).code == "CONSECUTIVE_LOSSES"
    assert check_ledger({"A": 10}, {"A": 9}).code == "LEDGER_MISMATCH"
```

- [ ] **Step 2: FAIL 확인**
- [ ] **Step 3: 구현**
- [ ] **Step 4: PASS**
- [ ] **Step 5: Commit** — `feat: risk rules, forced stop-loss, circuit breaker, auto-stop guards`

---

### Task 13: 모의 브로커, 모드, 승인 대기열, 실행기

**Files:**
- Create: `src/stockbot/broker/__init__.py`, `src/stockbot/broker/base.py`, `src/stockbot/broker/paper.py`, `src/stockbot/execution/__init__.py`, `src/stockbot/execution/routing.py`, `src/stockbot/execution/approvals.py`, `src/stockbot/execution/executor.py`, `src/stockbot/notify.py`, `tests/execution/test_paper.py`, `tests/execution/test_executor.py`
- Modify: `models.py` (테이블 `orders(id, idempotency_key UNIQUE, ticker, side, qty, kind, limit_price, expires_at, status, fill_price, fill_qty, commission, decision_id, reason, created_at, filled_at, broker)`, `paper_positions(ticker PK, qty, avg_price)`, `paper_cash(id=1, cash, peak_equity)`, `approvals(id, order_id, status, expires_at, decided_at)`)

**Interfaces:**
- Consumes: Task 12 `OrderIntent`, `PositionView`, `FillRecord`, `check_quote`
- Produces:
  - `Quote(ticker, price: float, ts: datetime, prev_close: float)`; `OrderResult(status: Literal["filled","open","rejected"], fill_price: float | None, fill_qty: int, order_id: int, message: str = "")`
  - `Broker(Protocol)`: `name: str`; `get_quote(ticker) -> Quote`; `place(intent: OrderIntent, now: datetime) -> OrderResult`; `positions() -> dict[str, PositionView]`; `cash() -> float`; `process_open_orders(now) -> list[OrderResult]`; `fills_since(since: datetime) -> list[FillRecord]`
  - `PaperBroker(session_factory, quote_fn: Callable[[str], Quote], initial_cash: float, slippage_bps: float = 5, commission_rate: float = 0.0025)` — 시장가: 매수 price×(1+5bp), 매도 price×(1−5bp), 수수료 = 체결금액×0.25%; 지정가 매수는 `open`으로 두고 `process_open_orders`에서 quote ≤ limit이면 limit에 체결, `expires_at` 지나면 `expired`; 같은 `idempotency_key`면 기존 주문 결과 반환; `check_quote` 실패 시 `rejected`
  - `routing.route(intents, mode: ModeState, rebuy_auto: bool) -> tuple[list[OrderIntent], list[OrderIntent]]` → (자동, 승인 필요). semi: sell/trim/stop_loss/switch_sell 자동, rebuy는 `rebuy_auto`면 자동, new_buy/add/switch_buy 승인 필요. auto: 전부 자동
  - `ApprovalQueue(session_factory)`: `create(order_id: int, expires_at: datetime) -> int`, `approve(approval_id, now) -> Literal["ok","expired","already"]`, `reject(approval_id, now) -> Literal["ok","expired","already"]`, `pending(now) -> list[ApprovalRow]`, `expire(now) -> list[int]`
  - `Notifier(Protocol)`: `send(text: str, buttons: list[tuple[str, str]] | None = None) -> None` (버튼 = (라벨, callback_data)); `ListNotifier`(테스트용, `messages`)
  - `Executor(session_factory, broker: Broker, approvals: ApprovalQueue, notifier: Notifier)`:
    - `stage(intents: list[OrderIntent], mode: ModeState, rebuy_auto: bool, approval_expires_at: datetime) -> StageReport` — 모든 intent를 `orders`에 `staged`로 저장(idempotency_key UNIQUE로 중복 무시), 승인 필요 건은 approvals 생성 + 버튼 알림(`approve:<id>`, `reject:<id>`)
    - `execute_ready(now: datetime) -> list[OrderResult]` — `staged` 자동 건 + 승인된 건을 브로커로 전송(매도 먼저), 만료 처리
    - `execute_now(intents, now) -> list[OrderResult]` — 긴급 방어 매도 즉시 전송(stage 후 바로 execute)

- [ ] **Step 1: 실패하는 테스트 작성**

```python
def test_paper_fill_with_slippage_and_commission(paper):   # quote 100
    r = paper.place(buy("T", 10, key="k1"), NOW)
    assert r.fill_price == pytest.approx(100.05) and paper.cash() == pytest.approx(10_000 - 1000.5 - 2.50125)

def test_idempotent_order(paper):
    a = paper.place(buy("T", 10, key="same"), NOW); b = paper.place(buy("T", 10, key="same"), NOW)
    assert a.order_id == b.order_id and paper.positions()["T"].qty == 10

def test_paper_broker_refuses_bad_quote(paper_with_quote_0):
    assert paper_with_quote_0.place(buy("T", 1, key="z"), NOW).status == "rejected"

def test_resting_limit_rebuy(paper_quotes):   # quotes: 95 then 89
    r = paper_quotes.place(rebuy("T", 10, limit=90, expires=NOW + timedelta(days=30)), NOW); assert r.status == "open"
    assert paper_quotes.process_open_orders(NOW + timedelta(hours=1))[0].fill_price == 90

def test_semi_routing():
    auto, need = route([sell_i(), stop_i(), rebuy_i(), buy_i(), add_i(), switch_buy_i()], ModeState(), rebuy_auto=True)
    assert {i.kind for i in auto} == {"sell", "stop_loss", "rebuy"} and {i.kind for i in need} == {"new_buy", "add", "switch_buy"}
    assert route([buy_i()], ModeState(automation="auto"), True)[1] == []

def test_double_approve_and_expiry(queue):
    aid = queue.create(order_id=1, expires_at=NOW + timedelta(hours=1))
    assert queue.approve(aid, NOW) == "ok" and queue.approve(aid, NOW) == "already"
    aid2 = queue.create(order_id=2, expires_at=NOW)
    assert queue.approve(aid2, NOW + timedelta(seconds=1)) == "expired"

def test_executor_flow(executor, notifier):
    executor.stage([sell_i("A"), buy_i("B")], ModeState(), True, approval_expires_at=OPEN)
    assert any("approve:" in b[1] for m in notifier.messages for b in (m.buttons or []))
    results = executor.execute_ready(OPEN)
    assert [r.status for r in results] == ["filled"]          # B는 미승인 → 실행 안 됨, 만료
```

- [ ] **Step 2: FAIL 확인**
- [ ] **Step 3: 구현**
- [ ] **Step 4: PASS**
- [ ] **Step 5: Commit** — `feat: paper broker, approval queue, semi/auto routing, executor`

---

### Task 14: 하루 사이클 파이프라인과 뉴스 감시

**Files:**
- Create: `src/stockbot/pipeline/__init__.py`, `src/stockbot/pipeline/deps.py`, `src/stockbot/pipeline/context.py`, `src/stockbot/pipeline/daily.py`, `src/stockbot/pipeline/news_watch.py`, `src/stockbot/health.py`, `tests/pipeline/test_daily.py`, `tests/pipeline/test_news_watch.py`, `tests/pipeline/fakes.py`
- Modify: `models.py` (테이블 `health_events(id, component, ok, detail, at)`, `guard_events(id, code, message, at, cleared_at)`)

**Interfaces:**
- Consumes: Task 3~13 전부
- Produces:
  - `Health(session_factory)`: `record(component: str, ok: bool, detail: str, now)`, `degraded() -> bool` (어느 컴포넌트든 최근 3회 연속 실패), `status() -> dict[str, dict]`
  - `Deps` (dataclass): `session_factory, settings, prices: PriceStore, news: NewsStore, news_sources: list[NewsSource], scorer: SentimentScorer, engine: DebateEngine, scoreboard: Scoreboard, broker: Broker, executor: Executor, approvals: ApprovalQueue, notifier: Notifier, health: Health, chart_dir: Path`
  - `context.build_context(deps, ticker, as_of, kind, holding) -> DebateContext` (차트 신호 텍스트, 지표 요약, PNG 바이트, 최근 3일 관련 뉴스 상위 8개 제목+태그, 거시 요약: 유가·10년물·VIX·달러 5일 변화율, 점수판)
  - `DailyCycle(deps)`:
    - `post_close(session_date: date, now: datetime) -> CycleReport` — 순서: 가격·뉴스 갱신(실패 시 health 기록) → `scoreboard.grade_due` → 강제 손절 intents → `screen` → 각 후보 토론 → `record_debate` → `decision_to_intents` → 가드·서킷브레이커 확인(걸리면 `mode.paused=True`, `pause_reason`, 알림) → `apply_risk` → `executor.stage(approval_expires_at=다음 개장)`; health.degraded면 매수 intents 제거
    - post_close 끝에 `BudgetTracker.state`가 이전 실행 대비 `alert`/`capped`로 바뀌었으면 알림 (`"이번 달 AI 비용 $8.50 / $10 (85%)"`)
    - `pre_open(session_date, now) -> CycleReport` — 마지막 post_close 이후 보유 종목 관련 심각도 ≥ threshold 뉴스가 있으면 긴급 토론 → 방어 intents stage
    - `at_open(session_date, now) -> list[OrderResult]` — `executor.execute_ready(now)`, 결과 알림
  - `CycleReport(debates: list[int], staged: list[int], rejected: list[tuple[str, str]], paused: bool, notes: list[str])`
  - `NewsWatcher(deps)`: `poll(now) -> list[int]` (debate ids) — 모든 소스 fetch → scorer → `assess` → 저장 → `NewsVerifier.update(now)` → 보유 종목 relevance ≥ 1 이고 severity ≥ `severity_threshold`인 묶음 중 **`confirmed`로 새로 바뀐 것**마다 긴급 토론(종목당 2시간에 1회) → 장중이면 매도 쪽 intents `execute_now`, 장외면 stage + 알림. 같은 조건인데 `unconfirmed`면 토론 없이 `"확인 중: …"` 알림 1회만(묶음당), `contradicted`면 무시
  - `context.build_context`의 뉴스 요약은 `digest_line` 형식, `contradicted` 묶음은 "반박된 루머" 별도 줄로만 표시
  - `Deps`에 `verifier: NewsVerifier` 추가

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/pipeline/fakes.py`: `make_deps(...)` — 인메모리 DB, 가짜 가격/뉴스/라우터, `ListNotifier`)

```python
def test_post_close_debates_only_screened(deps):
    rep = DailyCycle(deps).post_close(date(2024, 6, 3), NOW)
    assert len(rep.debates) == 5

def test_degraded_health_blocks_buys(deps_all_buy):
    for _ in range(3): deps_all_buy.health.record("prices", False, "x", NOW)
    rep = DailyCycle(deps_all_buy).post_close(date(2024, 6, 3), NOW)
    assert all(o.side == "sell" for o in staged_orders(deps_all_buy))

def test_guard_trip_pauses_and_notifies(deps_churn):
    rep = DailyCycle(deps_churn).post_close(date(2024, 6, 3), NOW)
    assert rep.paused and any("자동 정지" in m.text for m in deps_churn.notifier.messages)

def test_open_rerun_does_not_duplicate(deps_auto):
    c = DailyCycle(deps_auto); c.post_close(date(2024, 6, 3), NOW)
    c.at_open(date(2024, 6, 4), OPEN); c.at_open(date(2024, 6, 4), OPEN)
    assert count_filled_orders(deps_auto) == count_auto_intents(deps_auto)

def test_war_news_triggers_emergency_sell_during_market(deps_holding_nvda_scripted_sell):
    d = deps_holding_nvda_scripted_sell; d.news_sources[0].queue(item("War breaks out, oil prices surge 12%"))
    ids = NewsWatcher(d).poll(MARKET_OPEN_NOW)
    assert len(ids) == 1 and filled_sells(d, "NVDA")

def test_unconfirmed_rumor_only_notifies(deps_holding_nvda_scripted_sell):
    d = deps_holding_nvda_scripted_sell; d.news_sources[0].queue(item("Nvidia factory destroyed in war strike", domain="smallblog.net"))
    assert NewsWatcher(d).poll(MARKET_OPEN_NOW) == [] and any(m.text.startswith("확인 중") for m in d.notifier.messages)
    d.news_sources[0].queue(item("Nvidia factory hit in strike, company confirms", domain="cnbc.com"),
                            item("Strike hits Nvidia supplier factory", domain="marketwatch.com"))
    assert len(NewsWatcher(d).poll(MARKET_OPEN_NOW + timedelta(minutes=10))) == 1

def test_budget_alert_notifies_once(deps_spend_8_5):
    c = DailyCycle(deps_spend_8_5); c.post_close(date(2024, 6, 3), NOW); c.post_close(date(2024, 6, 4), NOW2)
    assert sum("AI 비용" in m.text for m in deps_spend_8_5.notifier.messages) == 1

def test_low_severity_ignored(deps_holding_nvda_scripted_sell):
    d = deps_holding_nvda_scripted_sell; d.news_sources[0].queue(item("NVIDIA opens new office"))
    assert NewsWatcher(d).poll(MARKET_OPEN_NOW) == []
```

- [ ] **Step 2: FAIL 확인**
- [ ] **Step 3: 구현**
- [ ] **Step 4: PASS**
- [ ] **Step 5: Commit** — `feat: daily cycle pipeline and news watcher with emergency debates`

---

### Task 15: 일일 보고서(투자 설명회)와 Q&A

**Files:**
- Create: `src/stockbot/report/__init__.py`, `src/stockbot/report/daily_report.py`, `src/stockbot/report/qa.py`, `tests/report/test_report.py`

**Interfaces:**
- Consumes: Task 8 `LLMRouter`, Task 10 `debates` 테이블, Task 13 approvals, Task 14 `Deps`
- Produces:
  - `ReportData(session_date, market_lines: list[str], top_news: list[NewsItem], trend_lines: list[str], holdings: list[PositionView], proposals: list[ProposalLine], equity: float, vs_spy_pct: float | None, cost_state: str)`; `ProposalLine(debate_id, ticker, action, shares_text: str, referee_summary: str, approval_id: int | None)`
  - `collect_report_data(deps, session_date) -> ReportData`
  - `render_report(data: ReportData, narrative: dict[str, str] | None) -> str` — 섹션 제목 고정·순서 고정: `"1. 전날 시장 요약"`, `"2. 주요 뉴스와 영향"`, `"3. 최근 동향"`, `"4. 보유 종목 점검"`, `"5. 오늘의 제안"`; `narrative`가 없으면 데이터만으로 템플릿 작성; 텔레그램 4096자 제한에 맞게 `split_message(text, 4000) -> list[str]`
  - `write_narrative(router, data, now) -> dict[str, str] | None` (좌석 id `"reporter"`, 실패 시 None)
  - `answer_question(router, question: str, context_text: str, now) -> str` (좌석 id `"reporter"`, 실패 시 `"지금은 답변할 수 없어요. 잠시 후 다시 물어봐 주세요."`); `build_qa_context(deps, session_date) -> str` (오늘 보고서 + 토론 요약 + 보유)
  - `send_daily_report(deps, session_date, now) -> None` (보고서 분할 전송 + 승인 대기 건마다 버튼)

- [ ] **Step 1: 실패하는 테스트 작성**

```python
def test_sections_in_order():
    text = render_report(sample_data(), None)
    idx = [text.index(h) for h in ["1. 전날 시장 요약", "2. 주요 뉴스와 영향", "3. 최근 동향", "4. 보유 종목 점검", "5. 오늘의 제안"]]
    assert idx == sorted(idx)

def test_fallback_when_llm_fails():
    assert write_narrative(failing_router(), sample_data(), NOW) is None
    assert "5. 오늘의 제안" in render_report(sample_data(), None)

def test_split_message():
    parts = split_message("가" * 9000, 4000); assert len(parts) == 3 and all(len(p) <= 4000 for p in parts)

def test_qa_failure_message():
    assert answer_question(failing_router(), "왜 팔았어?", "ctx", NOW).startswith("지금은 답변할 수 없어요")
```

- [ ] **Step 2: FAIL 확인**
- [ ] **Step 3: 구현**
- [ ] **Step 4: PASS**
- [ ] **Step 5: Commit** — `feat: daily briefing report and Q&A`

---

### Task 16: 텔레그램 봇

**Files:**
- Create: `src/stockbot/telegram/__init__.py`, `src/stockbot/telegram/commands.py`, `src/stockbot/telegram/bot.py`, `tests/telegram/test_commands.py`

**Interfaces:**
- Consumes: Task 13 `ApprovalQueue`, `Executor`, `Notifier`; Task 15 `answer_question`, `build_qa_context`; Task 1 `settings_store`
- Produces:
  - `Reply(text: str, buttons: list[tuple[str, str]] | None = None)`
  - `CommandService(deps, settings)`: `handle_text(chat_id: int, text: str, now) -> Reply | None` (허용 chat id 아니면 None), `handle_callback(chat_id, data: str, now) -> Reply | None`
  - 명령: `/status`, `/report`, `/positions`, `/pending`, `/auto on|off`, `/pause`, `/resume`, `/stop`, `/liquidate`, `/mode paper|real`, `/budget <금액>`, `/cost`, `/ask <질문>`, 그 외 일반 텍스트 = 질문
  - **PIN 필요**: `/auto on`, `/mode real`, `/budget`, `/resume`(서킷브레이커·가드로 멈춘 경우), `/liquidate`. 흐름: 명령 → "PIN을 입력하세요" → 같은 chat의 다음 메시지가 PIN(120초 유효, `hmac.compare_digest`) → 실행. 틀리면 취소. `/auto off`, `/pause`, `/stop`은 PIN 없이 즉시.
  - `/stop`: `mode.paused=True`, `pause_reason="사용자 긴급 정지"`. `/liquidate`: PIN 후 "정말 전량 매도? 예/아니오" 버튼 → `liquidate:yes` 콜백에서만 전량 매도 `execute_now`
  - `/mode real`: 실전 브로커가 설정돼 있지 않으면 `"실전 브로커가 아직 설정되지 않았습니다"` (실제 연결은 Plan 3)
  - 콜백: `approve:<id>`, `reject:<id>`, `detail:<debate_id>`, `liquidate:yes|no`; 결과 문구 `"승인했습니다"`, `"이미 처리된 건입니다"`, `"만료된 건입니다"`
  - `TelegramNotifier(Notifier)`, `run_bot(deps, settings, service) -> Application` (python-telegram-bot 폴링, 별도 스레드 이벤트 루프)

- [ ] **Step 1: 실패하는 테스트 작성**

```python
def test_unknown_chat_ignored(svc): assert svc.handle_text(999, "/status", NOW) is None

def test_auto_on_requires_pin(svc, deps):
    assert "PIN" in svc.handle_text(111, "/auto on", NOW).text
    assert svc.handle_text(111, "0000", NOW).text.startswith("PIN이 틀렸")
    assert load_mode(deps).automation == "semi"
    svc.handle_text(111, "/auto on", NOW); svc.handle_text(111, "1234", NOW)
    assert load_mode(deps).automation == "auto"

def test_pin_prompt_expires(svc, deps):
    svc.handle_text(111, "/auto on", NOW); svc.handle_text(111, "1234", NOW + timedelta(seconds=121))
    assert load_mode(deps).automation == "semi"

def test_stop_without_pin(svc, deps):
    svc.handle_text(111, "/stop", NOW); assert load_mode(deps).paused

def test_double_approve(svc, pending_approval_id):
    assert svc.handle_callback(111, f"approve:{pending_approval_id}", NOW).text == "승인했습니다"
    assert svc.handle_callback(111, f"approve:{pending_approval_id}", NOW).text == "이미 처리된 건입니다"

def test_approve_after_expiry(svc, expired_approval_id):
    assert svc.handle_callback(111, f"approve:{expired_approval_id}", NOW).text == "만료된 건입니다"

def test_mode_real_without_broker(svc):
    svc.handle_text(111, "/mode real", NOW); assert "설정되지 않았습니다" in svc.handle_text(111, "1234", NOW).text

def test_free_text_is_question(svc_with_scripted_reporter):
    assert svc_with_scripted_reporter.handle_text(111, "엔비디아 왜 팔았어?", NOW).text == "스크립트 답변"
```

- [ ] **Step 2: FAIL 확인**
- [ ] **Step 3: 구현** (`commands.py`는 telegram 라이브러리 import 없음; `bot.py`만 의존)
- [ ] **Step 4: PASS, lock 갱신**
- [ ] **Step 5: Commit** — `feat: telegram command service with PIN-guarded actions`

---

### Task 17: 웹 API와 로그인

**Files:**
- Create: `src/stockbot/web/__init__.py`, `src/stockbot/web/app.py`, `src/stockbot/web/auth.py`, `src/stockbot/web/routes.py`, `tests/web/test_api.py`

**Interfaces:**
- Consumes: Task 13~16 서비스 (승인·모드 변경은 `CommandService`와 같은 내부 함수 재사용: `commands.set_automation(deps, value)`, `commands.set_paused(...)`, `commands.decide_approval(...)` — Task 16에서 모듈 함수로 분리해 둘 것)
- Produces: `create_app(deps, settings, static_dir: Path | None) -> FastAPI`
  - `POST /api/login {password}` → itsdangerous 서명 쿠키(`stockbot_session`, 7일, HttpOnly, SameSite=Lax); 5회 연속 실패 시 5분 잠금
  - 인증 필요: `GET /api/dashboard` (equity, cash, positions, mode, pending_count, health, cost{spend, cap, state}, equity_curve[{date, equity, spy}]), `GET /api/debates?limit=20`, `GET /api/debates/{id}` (라운드별 의견·표결·설득·심판 요약), `GET /api/approvals`, `POST /api/approvals/{id}/approve|reject`, `GET /api/scoreboard`, `GET /api/news?min_severity=0`, `GET /api/settings`, `PATCH /api/settings` (risk/debate/cost 값 수정; `mode.automation="auto"`, `mode.broker="real"`, `budget_usd` 변경, 가드 정지 해제는 본문에 `pin` 필요, 틀리면 403), `GET /api/health`
  - `static_dir`가 있으면 `/`에 SPA 정적 파일(없는 경로는 index.html)

- [ ] **Step 1: 실패하는 테스트 작성** (FastAPI `TestClient`)

```python
def test_requires_login(client): assert client.get("/api/dashboard").status_code == 401
def test_wrong_password(client): assert client.post("/api/login", json={"password": "x"}).status_code == 401
def test_login_then_dashboard(client):
    client.post("/api/login", json={"password": "pw"})
    body = client.get("/api/dashboard").json(); assert body["mode"]["broker"] == "paper" and "cost" in body
def test_lockout(client):
    for _ in range(5): client.post("/api/login", json={"password": "x"})
    assert client.post("/api/login", json={"password": "pw"}).status_code == 429
def test_auto_mode_needs_pin(authed):
    assert authed.patch("/api/settings", json={"mode": {"automation": "auto"}}).status_code == 403
    assert authed.patch("/api/settings", json={"mode": {"automation": "auto"}, "pin": "1234"}).status_code == 200
def test_approve_endpoint(authed, pending_approval_id):
    assert authed.post(f"/api/approvals/{pending_approval_id}/approve").json()["result"] == "ok"
    assert authed.post(f"/api/approvals/{pending_approval_id}/approve").json()["result"] == "already"
```

- [ ] **Step 2: FAIL 확인**
- [ ] **Step 3: 구현**
- [ ] **Step 4: PASS, lock 갱신**
- [ ] **Step 5: Commit** — `feat: web API with session login and PIN-guarded settings`

---

### Task 18: 웹 관리페이지 (휴대폰 우선)

**Files:**
- Create: `web-ui/` (Vite React TS: `package.json`, `vite.config.ts`(개발 시 `/api` → `http://127.0.0.1:8000` 프록시), `index.html`, `src/main.tsx`, `src/api.ts`, `src/pages/Login.tsx`, `src/pages/Dashboard.tsx`, `src/pages/Debates.tsx`, `src/pages/DebateDetail.tsx`, `src/pages/Approvals.tsx`, `src/pages/Settings.tsx`, `src/pages/News.tsx`, `src/pages/Scoreboard.tsx`, `src/styles.css`)

**Interfaces:**
- Consumes: Task 17 API 그대로
- 화면: 하단 탭바(대시보드·토론·승인·뉴스·설정), 폭 360px 기준 레이아웃, 다크/라이트 자동. 대시보드 = 총자산·수익률·모드 배지·자산 추이(Recharts, SPY 비교선)·보유 목록·승인 대기 수·상태(데이터/LLM/비용 spend/cap). 토론 상세 = 라운드별 좌석 카드(팀 색 구분, 행동·확신도·근거), 표결 점유율 막대, 설득 표시, 심판 요약. 설정 = 리스크 값 폼, 좌석-제공자 표(읽기 전용, Plan 2에서 편집), 모드 토글(PIN 입력 모달). 모든 문구 한국어.

- [ ] **Step 1: `npm create vite@latest web-ui -- --template react-ts`, `npm i recharts react-router-dom`**
- [ ] **Step 2: 페이지 구현** — 스타일·구성은 `frontend-design` 스킬 지침을 따른다
- [ ] **Step 3: `cd web-ui && npm run build` → `dist/` 생성, 타입 오류 0 확인**
- [ ] **Step 4: 수동 확인** — 백엔드를 가짜 데이터로 띄우고(`python -m stockbot --demo`, Task 19) 브라우저 모바일 화면(390×844)에서 로그인→대시보드→토론 상세→승인→설정 PIN 모달 동작 확인 (`run` / `webapp-testing` 스킬로 스크린샷)
- [ ] **Step 5: Commit** — `feat: mobile-first admin web UI`

---

### Task 19: 스케줄러, 실행 진입점, 데모 모드

**Files:**
- Create: `src/stockbot/scheduler.py`, `src/stockbot/app_factory.py`, `src/stockbot/__main__.py`, `src/stockbot/demo.py`, `start.bat`, `tests/test_scheduler.py`

**Interfaces:**
- Consumes: 전부
- Produces:
  - `ScheduledJob(name: Literal["post_close","report","pre_open","open"], run_at: datetime(KST), session_date: date)`
  - `plan_jobs(kst_day: date, cfg: RuntimeConfig) -> list[ScheduledJob]` — 순수 함수. 그 KST 날짜에 일어날 작업: 직전 세션의 `post_close` = 폐장+30분, `report` = `report_time_kst`(다음 개장이 그 KST 날짜에 있을 때만), 다음 세션의 `pre_open` = 개장−30분, `open` = 개장
  - `start_scheduler(deps, cycle: DailyCycle, watcher: NewsWatcher, cfg) -> BackgroundScheduler` — 매일 00:05 KST에 그날 `plan_jobs`를 date 트리거로 등록, 뉴스 폴링 `news_poll_minutes` 간격 interval 트리거, 각 작업 예외는 `health.record`(실패)로 남기고 3회 연속 실패 시 알림
  - `build_deps(settings, runtime_cfg) -> Deps` (실제 구현체 조립: `YFinanceFetcher`, `RssSource`+`FinnhubSource`, `get_scorer()`, `build_router`, `PaperBroker(quote_fn=Finnhub 시세, initial_cash=budget_usd)`, `TelegramNotifier` 또는 토큰 없으면 콘솔 로거)
  - `python -m stockbot` → DB 초기화, uvicorn(`127.0.0.1:8000`) + 스케줄러 + 텔레그램; `--dry-run` → 오늘·내일 `plan_jobs`와 `health.status()` 출력 후 종료(코드 0); `--demo` → 가짜 데이터로 채운 임시 DB로 웹만 실행
  - `start.bat` → `.venv\Scripts\python -m stockbot`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
def test_winter_day_jobs():
    jobs = {j.name: j for j in plan_jobs(date(2026, 12, 2), RuntimeConfig())}
    assert jobs["post_close"].run_at == datetime(2026, 12, 2, 6, 30, tzinfo=KST) and jobs["post_close"].session_date == date(2026, 12, 1)
    assert jobs["report"].run_at == datetime(2026, 12, 2, 17, 30, tzinfo=KST)
    assert jobs["pre_open"].run_at == datetime(2026, 12, 2, 23, 0, tzinfo=KST)
    assert jobs["open"].run_at == datetime(2026, 12, 2, 23, 30, tzinfo=KST)

def test_dst_shift():
    jobs = {j.name: j for j in plan_jobs(date(2026, 7, 2), RuntimeConfig())}
    assert jobs["post_close"].run_at == datetime(2026, 7, 2, 5, 30, tzinfo=KST) and jobs["open"].run_at == datetime(2026, 7, 2, 22, 30, tzinfo=KST)

def test_no_jobs_on_holiday():
    names = {j.name for j in plan_jobs(date(2026, 12, 25), RuntimeConfig())}   # 12/24 세션 폐장 03:00(조기폐장)+30분은 있음, 12/25 개장 없음
    assert "open" not in names and "report" not in names and "pre_open" not in names

def test_dry_run_exits_zero(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKBOT_DB_URL", f"sqlite:///{tmp_path}/t.db"); ...
    assert subprocess.run([sys.executable, "-m", "stockbot", "--dry-run"], capture_output=True).returncode == 0
```

- [ ] **Step 2: FAIL 확인**
- [ ] **Step 3: 구현**
- [ ] **Step 4: PASS, 전체 `pytest -q` PASS, lock 갱신**
- [ ] **Step 5: 수동 확인** — 실제 `.env`로 `start.bat` 실행 → 텔레그램 `/status` 응답, 웹 `http://127.0.0.1:8000` 로그인, `--dry-run` 출력의 시각이 오늘 KST 기준으로 맞는지 확인
- [ ] **Step 6: Commit** — `feat: scheduler, entry point, demo mode`

---

## 완료 기준

- `pytest -q` 전부 통과 (network/slow 제외)
- PC에서 `start.bat` 실행 시: 텔레그램 `/status`·`/report` 응답, 웹 로그인·대시보드 표시, `--dry-run` 시각 정확
- 하루 동안 실제로 켜 두었을 때 post_close 토론 → 17:30 보고서 → 승인 버튼 → 개장 시 모의 체결이 기록됨
