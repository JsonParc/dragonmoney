# Plan 1 — 실행 중 내린 판단(Ruling)과 보류한 사소한 지적

구현 중 계획과 다르게 하거나 계획이 정하지 않은 부분을 결정한 기록입니다. 각 줄: 무엇을 정했나 — 이유 — 틀렸을 때 비용.

## 판단(Ruling)
- - T8 → T10/T15: router chains must exist for seat ids incl. "referee", "reporter". Ruling: build_router creates a chain for every DEFAULT_SEATS id + "referee" + "reporter" — spec §7.5/§7.9 need them — cost if wrong: KeyError at runtime.
- - T13 Quote → T19 build_deps "Finnhub 시세" quote_fn: no task defines it. Ruling: T19 adds src/stockbot/data/quotes.py `finnhub_quote_fn(api_key) -> Callable[[str], Quote]` (Finnhub /quote: c, pc, t) with a test using a fake HTTP transport — spec §7.1 server quotes = Finnhub in paper mode — cost if wrong: paper broker has no live price.
- Task 4: Ruling: get_bars reads DB only; only ensure() fetches (coverage table) — keeps reads as-of/deterministic and the cache-hit test exact — cost if wrong: callers must call ensure() before reading (pipeline does)
- Task 4: Ruling: network test expected 5 bars for 2024-01-02..09; real count is 6 sessions — test value fixed — none
- Task 2: Ruling: LLM free-tier measurement not done (no Gemini/Groq keys in .env); provisional seat table recorded, re-measure in Task 8 network test once keys exist — cost if wrong: default model IDs may be stale
- Task 5: Ruling: plan test_golden_cross compared last vs prev of [100]*30+[101,103,106,110] where neither day crosses — replaced with cross-day / day-after / flat series — none
- Task 5: Ruling: added tests for dead cross, aligned_bear+rsi_oversold, box_breakout, long_bull_candle, short history — cover rules the brief fixes — none
- Task 6: Ruling: found RSI=100 on flat series (Task 5 bug) — fixed with test_flat_series_rsi_is_neutral RED→GREEN — none
- Task 6: Ruling: held tickers are excluded from fresh candidates (only flagged holdings debated) — spec §7.4 — cost if wrong: no ADD proposals on unflagged holdings
- Task 7: Ruling: dedupe is by url OR (domain, normalized title) — not title alone as the brief test implied — because Task 7b cross-verification must keep every outlet copy — cost if wrong: duplicate rows for same-title syndication (counted once in 7b anyway)
- Task 7: Ruling: source list/tiers in data_static/news_sources.toml (tomllib) instead of yaml — no extra dependency — none
- Task 7: Ruling: SEC EDGAR uses generic User-Agent (no personal email, per privacy rule); SEC may reject it → source just yields nothing — cost if wrong: no tier-0 filings until a contact UA is configured
- Task 7b: Ruling: verification/independent_sources live only on news_clusters (news_items keeps cluster_id) — single source of truth — none
- Task 7b: Ruling: denial stories join a rumor cluster at similarity >=0.3 when they share a ticker — otherwise a denial never meets the 0.6 threshold and contradiction could not be detected — cost if wrong: unrelated same-ticker denials may merge
- Task 7b: Ruling: Jaccard similarity is default; embedding hook (embed=callable) exists but is not wired to sentence-transformers yet (Plan 2) — cost if wrong: paraphrased headlines may not cluster
- Task 8: Ruling: blank .env model ids default to provisional free-tier ids (gemini-2.5-flash/-lite, groq llama-3.3-70b, qwen3-32b, llama-4-scout) overridable via STOCKBOT_*_MODEL — spike could not verify (no keys) — cost if wrong: provider 404s → router falls through to next provider
- Task 8: Ruling: Anthropic default model claude-opus-5-5 (skill default), placed LAST in every chain after free providers, with server-side refusal fallback; no temperature sent — cost if wrong: if used often it hits the $10 cap fast → set STOCKBOT_ANTHROPIC_MODEL=claude-haiku-5-5
- Task 8: Ruling: live network test skipped (no keys) — must run once keys exist
- Task 9: Ruling: detect_persuasion computes round-0 team positions with equal weights (signature has no weights) — persuasion is about who argued, not vote power — none
- Task 10: Ruling: when every seat failed (no valid opinion) deadlock=False and rebuttal rounds stop early — a provider outage is not the teams fault and must not burn more calls or trigger the deadlock penalty — cost if wrong: none
- Task 10: Ruling: round 0 is asked in parallel without teammates seeing each other; teammates see each other from round 1 with the other team — avoids anchoring, same cost — cost if wrong: slightly weaker team caucus
- Task 10: Ruling: actions are coerced to the position (not held: sell-side→HOLD, ADD→BUY; held: BUY→ADD) — LLMs often name the wrong verb — cost if wrong: a seat intending SELL on a non-held ticker counts as HOLD
- Task 10: Ruling: anonymize masks ticker + ISO dates only; company names in news text are masked in Plan 2 (anonymization task) — cost if wrong: leakage in backtests until Plan 2
- Task 11: Ruling: grading uses the close exactly horizon trading days after the decision (not the grading day close), and per-seat deltas of one grading are summed before one EMA step — reproducible regardless of when the job runs — none
- Task 12: Ruling: apply_risk clips buy qty to min(budget room, cash, per-ticker 20% room) instead of rejecting outright; commission headroom is left to the broker (paper broker clips to cash after costs) — friendlier sizing — cost if wrong: one fewer share than expected
- Task 12: Ruling: SELL_REBUY without rebuy_price defaults to 5% below current price; rebuy expires at close of the 20th trading day — spec silent — cost if wrong: rebuy level may be arbitrary
- Task 12: Ruling: DATA_STALE only trips while the market is open — closed-market quotes are naturally old — none
- Task 13: Ruling: executor and broker share one orders table; broker.place executes only rows still "staged" (or new), so restarts never re-send — Review Focus #4 — none
- Task 13: Ruling: approval "자세히" button carries detail:<order_id> (order has decision_id) rather than debate_id — one lookup more — none
- Task 13: Ruling: PaperBroker.positions() reports last_price=avg_price; pipeline marks to market with quotes — avoids network in a getter — cost if wrong: callers forgetting to mark to market see zero PnL
- Task 14: Ruling: daily notional cap (30%) now TRIMS low-priority buys at staging (reported as "하루 매수 한도 … 보류"); the DAILY_ORDER_LIMIT auto-stop only trips on orders already recorded in the last 24h — otherwise a normal 5-candidate day paused the bot — cost if wrong: at most 30% of budget enters per day
- Task 14: Ruling: war-news tests queue two reputable outlets (single-source news is unconfirmed by design since Task 7b); rumor test titles made near-identical so they cluster — plan tests predated 7b — none
- Task 14: Ruling: PaperBroker gained realized_pnl per sell + realized_pnls() for the consecutive-loss guard — guard needed closed-trade PnL no task produced — none
- Task 14: Ruling: ledger-mismatch guard not wired for paper broker (broker is the book); wire it with the KIS adapter in Plan 3 — cost if wrong: none for paper
- Task 14: Ruling: pre_open = one NewsWatcher.poll (fetch+verify+emergency) — simplest form of the spec 23:00 re-check — cost if wrong: no premarket price-gap check yet
- Task 15: Ruling: collect_report_data/build_qa_context take `now` (needed for pending approvals and news recency); ReportData.top_news holds verified digest lines instead of NewsItem — reuses cross-check labels — none
- Task 15: Ruling: 17:30 report re-sends approval buttons for still-pending buys (the 06:30 request arrives while the user has no phone) — cost if wrong: duplicate buttons, both idempotent
- Task 16: Ruling: Telegram I/O is a ~100-line httpx client (sendMessage + getUpdates long-poll) instead of python-telegram-bot — sync code fits the scheduler threads, one less pinned dependency for 18 months unattended — cost if wrong: fewer Telegram features (none needed)
- Task 16: Ruling: /resume always needs PIN (not only after guard stops); /pause and /stop both pause new buys (stop wording differs) — spec lists /pause,/resume,/stop — none
- Task 16: Ruling: liquidate:yes is accepted only within 2 min after the PIN step in the same chat — prevents a stale/forwarded button from selling everything — none
- Task 17: Ruling: added equity_snapshots table written at post_close so the dashboard equity-vs-SPY curve has data (no task produced it) — none
- Task 17: Ruling: create_app takes now_fn (testability) and exposes public /healthz for Render health checks; all /api/* need the session cookie — none
- Task 17: Ruling: PATCH /api/settings with mode.broker=real but no real broker returns 409 (not 403) — distinguishes "not configured" from "bad PIN" — none
- Task 18: Ruling: Vite project files written by hand (create-vite is interactive); visual check deferred until Task 19 --demo exists, done right after it — none
- Task 18: Ruling: debate detail centers on a "debate floor" (seats placed in buy/hold/sell lanes per round, moved seats outlined) as the one distinctive element; rest is plain lists — design skill guidance — none
- Task 19: Ruling: report job is scheduled only on KST days with a session opening that evening; its session_date is the session closed that morning — matches approval window — none
- Task 19: Ruling: quote source = Finnhub when key exists, else yfinance 1-minute bars (PC only) — spec §7.1 — cost if wrong: yfinance may be rate limited
- Task 19: Ruling: manual check with a real .env (Telegram /status, live web login) NOT done — no keys yet; verified instead via --dry-run test and --demo with Playwright/Edge screenshots (light+dark, all 5 tabs, PIN modal) — cost if wrong: first real start may surface key/feed issues
- Final: Ruling: changed-by-design old tests updated (limit fill 90->89, open 23:30->23:35, risk edit now needs PIN) — follow the fixes — none

## 최종 검토 수정 내역
- Final: fixed C1 .gitignore data/ hid src/stockbot/data + tests/data — fresh-clone run 190/190 (commit 8b?) 
- Final: fixed C2 open-time stale quotes rejected every order — test_stale_quote_at_open_is_deferred_not_rejected, test_open_jobs_run_after_the_bell_with_retries RED→GREEN; DATA_STALE now defers (row stays staged), open job at +5m with retries +20m/+45m (final retry pauses if still stale)
- Final: fixed I3 bad quote pauses + alerts — test_bad_quote_at_open_pauses_and_alerts RED→GREEN
- Final: fixed I4 pause/breaker enforced at execution (staged buys cancelled, resting rebuys not filled) — test_paused_between_staging_and_open_blocks_buys, test_paused_blocks_resting_rebuy_fill RED→GREEN
- Final: fixed I5 staged expiry (open+7h), pending buys counted in apply_risk, startup catch-up of missed post_close/open — test_staged_orders_expire_after_their_session, test_pending_buys_count_against_limits, test_catch_up_runs_missed_post_close RED→GREEN
- Final: fixed I6 health gates only data components; debate success recorded — test_health_ignores_job_components_and_recovers RED→GREEN
- Final: fixed I7 quorum min_valid_seats=4 with both teams — test_quorum_required RED→GREEN
- Final: fixed I8 PIN-like text never forwarded to LLM; Telegram offset persisted (KVOffsetStore) — test_pin_never_forwarded RED→GREEN; also found compare_digest TypeError on Korean text (caught by test_free_text_is_question) and fixed with byte compare
- Final: fixed I9 denial patterns limited to rebuttals of reports/rumors; bankruptcy/fraud/regulatory_rejection tags — test_fda_denial_is_not_contradiction, test_company_shocks_reach_threshold RED→GREEN
- Final: fixed I10 emergency marked done only after a debate with valid answers — test_failed_emergency_is_retried RED→GREEN
- Final: fixed I11 execution lock + compare-and-set claim of staged rows — test_concurrent_execute_ready_fills_once RED→GREEN
- Final: fixed I12 limit buys fill at min(limit, market); rebuy price clamped ≤ 99% of market — test_limit_fills_at_market_when_lower, test_rebuy_price_clamped_below_market RED→GREEN
- Final: fixed I13 report session = previous trading day — test_monday_report_uses_previous_trading_day RED→GREEN
- Final: fixed I14 PIN for every non-conservative web change; PinGuard 5 tries / 5 min lock shared web+Telegram — test_risk_and_cost_edits_need_pin, test_pin_attempts_are_limited RED→GREEN; suite 210/210

## 보류한 사소한 지적
- Final: minor (deferred): AnthropicClient ignores req.max_tokens (16000 hard-coded); reviewer suggests Haiku default instead of Opus fallback; parallel calls can overshoot $10 cap slightly
- Final: minor (deferred): auth lockout counter is global (anyone can lock owner out 5 min); cookie lacks Secure flag (needed once served over HTTPS in Plan 3)
- Final: minor (deferred): emergency debate as_of uses KST date (may be a non-session date)
- Final: minor (deferred): TelegramNotifier ignores ok:false responses
