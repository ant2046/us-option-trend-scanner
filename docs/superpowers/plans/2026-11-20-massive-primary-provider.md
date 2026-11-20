# Massive Primary Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Massive the primary source for stock bars, premarket quotes, and news while preserving Yahoo as a dimension-level fallback.

**Architecture:** Add a focused Massive REST client and provider implementations behind the project's existing market-data and enrichment interfaces. Compose Massive with existing Yahoo implementations at dependency assembly time, retaining current scoring, reporting, and delivery behavior.

**Tech Stack:** Python 3.11+, requests, pandas, yfinance, pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-20-massive-primary-provider-design.md`

## Global Constraints

- Read `MASSIVE_API_KEY` only from the environment; never log it or a complete authenticated URL.
- Do not change the watchlist, trend rules, premarket thresholds, scoring semantics, report layout, or schedule.
- Massive is primary only for stock bars, premarket quotes, and news in this iteration.
- Fundamentals and options remain on Yahoo because the current Massive entitlement does not provide the required endpoints.
- Missing keys and provider failures must preserve a usable Yahoo-only run.
- A stale Massive premarket quote may fall back to a fresher Yahoo quote.

## Review Focus

- A Massive payload with timestamps in milliseconds at a UTC day boundary must map to the correct America/New_York session; pinned in Task 2.
- A paginated response whose second page fails must not return silently truncated history; pinned in Task 1.
- A 200 response containing malformed or empty results must trigger fallback rather than a false success; pinned in Tasks 2 and 3.
- A stale Massive quote plus an errored Yahoo quote must retain the stale Massive evidence instead of losing all quote context; pinned in Task 3.
- Exception text containing request URLs or query parameters must be sanitized before logging or surfacing; pinned in Task 1.

---

### Task 1: Configuration and Massive REST client

**Files:**
- Modify: `src/market_scanner/config.py`
- Create: `src/market_scanner/massive.py`
- Modify: `tests/test_config.py`
- Create: `tests/test_massive.py`

**Interfaces:**
- Consumes: environment variables `MASSIVE_API_KEY`, optional `MASSIVE_BASE_URL`, existing provider timeout/retry settings.
- Produces: `MassiveClient(api_key: str, *, base_url: str, timeout_seconds: int, retries: int, session=None, sleep=time.sleep)` and `MassiveError`; `MassiveClient.get(path: str, params: Mapping[str, object] | None = None, *, paginate: bool = False) -> tuple[dict, ...] | dict`.

- [ ] **Step 1: Write failing configuration tests**

Add tests asserting `Settings.from_env()` accepts a missing Massive key, reads a present key without altering it, and supplies the default base URL `https://api.massive.com`.

- [ ] **Step 2: Run the configuration tests and verify failure**

Run: `python -m pytest tests/test_config.py -q`
Expected: FAIL because Massive settings do not exist.

- [ ] **Step 3: Add Massive settings**

Add `massive_api_key: str | None`, `massive_base_url: str`, and reuse `provider_timeout_seconds` / `provider_retries` for the client.

- [ ] **Step 4: Write failing REST client tests**

Test successful JSON, relative `next_url` pagination, 401/403 without retry, 429/5xx retry, timeout retry, malformed JSON, empty second-page failure, and sanitization of an exception containing `apiKey=secret-value`.

- [ ] **Step 5: Run the client tests and verify failure**

Run: `python -m pytest tests/test_massive.py -q`
Expected: FAIL because `market_scanner.massive` does not exist.

- [ ] **Step 6: Implement the minimal REST client**

Authenticate with an `Authorization: Bearer` header. For pagination, accumulate complete `results` and fail the entire call if any page fails. Retry only timeout/connection errors, HTTP 429, and HTTP 5xx with bounded exponential backoff.

- [ ] **Step 7: Run Task 1 tests**

Run: `python -m pytest tests/test_config.py tests/test_massive.py -q`
Expected: PASS.

- [ ] **Step 8: Commit Task 1**

```bash
git add src/market_scanner/config.py src/market_scanner/massive.py tests/test_config.py tests/test_massive.py
git commit -m "feat: add Massive API client"
```

### Task 2: Massive stock bars adapter

**Files:**
- Create: `src/market_scanner/massive_data.py`
- Create: `tests/test_massive_data.py`

**Interfaces:**
- Consumes: `MassiveClient.get(...)`, the existing `MarketDataError`, `PremarketQuote`, `QuoteStatus`, and XNYS calendar rules.
- Produces: `MassiveMarketData(client: MassiveClient, *, stale_minutes: int = 15, calendar=None)` with `daily_history(symbol: str, completed_before: datetime) -> pd.DataFrame` and `premarket_quote(symbol: str, now: datetime) -> PremarketQuote`.

- [ ] **Step 1: Write failing daily-history tests**

Test aggregate mapping `o/h/l/c/v/t` to `Open/High/Low/Close/Volume`, ascending index, America/New_York timestamp conversion across a UTC date boundary, exclusion of incomplete current-session bars, previous-session validation, and rejection of empty/malformed results.

- [ ] **Step 2: Write failing premarket tests**

Test filtering to local 04:00–09:30, exclusion of future bars, latest valid close selection, exact stale threshold behavior, and empty/malformed response statuses.

- [ ] **Step 3: Run tests and verify failure**

Run: `python -m pytest tests/test_massive_data.py -q`
Expected: FAIL because `MassiveMarketData` does not exist.

- [ ] **Step 4: Implement `MassiveMarketData`**

Request six months of daily aggregates and the current local date's minute aggregates. Convert millisecond epoch values via UTC before converting to the caller's timezone, then apply the existing validation semantics.

- [ ] **Step 5: Run Task 2 tests**

Run: `python -m pytest tests/test_massive_data.py -q`
Expected: PASS.

- [ ] **Step 6: Commit Task 2**

```bash
git add src/market_scanner/massive_data.py tests/test_massive_data.py
git commit -m "feat: add Massive stock market data"
```

### Task 3: Market-data fallback composition

**Files:**
- Modify: `src/market_scanner/data.py`
- Modify: `tests/test_data.py`

**Interfaces:**
- Consumes: two objects implementing `daily_history` and `premarket_quote`.
- Produces: `FallbackMarketData(primary: object, fallback: object)` with the same two methods.

- [ ] **Step 1: Write failing fallback tests**

Assert the fallback is not called on valid primary results; daily exceptions/invalid frames call fallback; `ERROR`, `MISSING`, and `STALE` quotes call fallback; an OK fallback wins; and a stale primary is retained when the fallback errors or has less information.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_data.py -q`
Expected: FAIL because `FallbackMarketData` does not exist.

- [ ] **Step 3: Implement `FallbackMarketData`**

Validate daily frames before accepting them. Rank quote usefulness as OK, STALE, then MISSING/ERROR, preferring the newer observation when statuses tie.

- [ ] **Step 4: Run Task 3 tests**

Run: `python -m pytest tests/test_data.py tests/test_massive_data.py -q`
Expected: PASS.

- [ ] **Step 5: Commit Task 3**

```bash
git add src/market_scanner/data.py tests/test_data.py
git commit -m "feat: add resilient market data fallback"
```

### Task 4: Massive news provider and Yahoo fallback

**Files:**
- Modify: `src/market_scanner/event_news.py`
- Modify: `tests/test_event_news.py`

**Interfaces:**
- Consumes: `MassiveClient`, `MacroCalendar`, existing `ProviderResult` / evidence models, and an optional Yahoo news provider.
- Produces: `MassiveEventNewsProvider(client: MassiveClient, *, macro_calendar: MacroCalendar, settings: Settings | None = None)` and `FallbackEventNewsProvider(primary: object, fallback: object)` implementing `assess(symbol: str, now: datetime) -> ProviderResult`.

- [ ] **Step 1: Write failing Massive news tests**

Test Massive `title`, `publisher.name`, `published_utc`, and `article_url` mapping; age filtering; duplicate removal; negative-keyword labels; macro-calendar evidence; malformed/empty results; and `source=massive` metadata.

- [ ] **Step 2: Write failing fallback tests**

Assert Yahoo is not called for usable Massive evidence; errors and unavailable/empty Massive news call Yahoo; fallback output records `source=yahoo_fallback` without changing scoring keys.

- [ ] **Step 3: Run tests and verify failure**

Run: `python -m pytest tests/test_event_news.py -q`
Expected: FAIL because Massive and fallback providers do not exist.

- [ ] **Step 4: Implement Massive and fallback news providers**

Share normalization helpers where they preserve the existing Yahoo behavior. Keep local macro-calendar failures isolated from news retrieval failures.

- [ ] **Step 5: Run Task 4 tests**

Run: `python -m pytest tests/test_event_news.py tests/test_scoring.py -q`
Expected: PASS.

- [ ] **Step 6: Commit Task 4**

```bash
git add src/market_scanner/event_news.py tests/test_event_news.py
git commit -m "feat: add Massive news with Yahoo fallback"
```

### Task 5: Dependency assembly, workflow, and documentation

**Files:**
- Modify: `src/market_scanner/main.py`
- Modify: `.github/workflows/premarket-scan.yml`
- Modify: `tests/test_main.py`
- Modify: `tests/test_workflow.py`
- Modify: `README.md`
- Modify: `docs/PROJECT_DESIGN.md`

**Interfaces:**
- Consumes: Tasks 1–4 implementations and the existing Yahoo providers.
- Produces: `_dependencies(settings: Settings) -> Dependencies` that uses Massive primary + Yahoo fallback when a key exists and Yahoo-only behavior otherwise.

- [ ] **Step 1: Write failing assembly tests**

Assert a configured key builds `FallbackMarketData` and `FallbackEventNewsProvider`; a missing key builds existing Yahoo-only providers; fundamentals and options remain Yahoo in both branches; no output contains the API key.

- [ ] **Step 2: Write failing workflow tests**

Assert the scheduled/send step injects `MASSIVE_API_KEY: ${{ secrets.MASSIVE_API_KEY }}` and the test/dry-run steps do not require the real secret.

- [ ] **Step 3: Run tests and verify failure**

Run: `python -m pytest tests/test_main.py tests/test_workflow.py -q`
Expected: FAIL because assembly and workflow are not wired.

- [ ] **Step 4: Wire runtime dependencies**

Construct one `MassiveClient`, a Massive/Yahoo market fallback, and a Massive/Yahoo event-news fallback when the key exists. Keep `YahooFundamentalsProvider` and `YahooOptionsProvider` unchanged.

- [ ] **Step 5: Update GitHub Actions and documentation**

Document provider ownership, the key requirement, fallback behavior, entitlement limitations, and troubleshooting without including any credential value.

- [ ] **Step 6: Run Task 5 tests**

Run: `python -m pytest tests/test_main.py tests/test_workflow.py -q`
Expected: PASS.

- [ ] **Step 7: Commit Task 5**

```bash
git add src/market_scanner/main.py .github/workflows/premarket-scan.yml tests/test_main.py tests/test_workflow.py README.md docs/PROJECT_DESIGN.md
git commit -m "feat: make Massive the primary market provider"
```

### Task 6: Full verification and live dry-run

**Files:**
- Modify only if verification exposes a defect in an already listed file.

**Interfaces:**
- Consumes: the completed provider composition.
- Produces: verified local and CI-ready behavior without sending a message.

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest -q`
Expected: all tests PASS.

- [ ] **Step 2: Run a credential-leak scan**

Run searches for the configured key value and authenticated URLs across tracked and untracked project files; expected: no matches.

- [ ] **Step 3: Run a real Massive dry-run**

Run: `python -m market_scanner.main --dry-run` with `MASSIVE_API_KEY` loaded from the user environment.
Expected: exit code 0 on an open session or the existing market-closed skip behavior; no enterprise WeChat send occurs.

- [ ] **Step 4: Inspect provider behavior**

Confirm logs/results show Massive use for accessible endpoints and Yahoo fallback only for unavailable dimensions or failed/stale requests, with no secrets printed.

- [ ] **Step 5: Commit verification fixes if required**

Commit only concrete fixes produced by Steps 1–4; do not create an empty verification commit.

