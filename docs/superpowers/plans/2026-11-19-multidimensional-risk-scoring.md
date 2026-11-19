# Multidimensional Risk Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add informational multidimensional scores, risk tags, evidence, completeness, and a mobile-readable WeCom report without changing the existing technical candidate set or ordering.

**Architecture:** Keep `SignalEngine` authoritative for selection, then enrich only selected candidates through four provider protocols. Convert provider results into standard immutable models, score known evidence without treating missing data as zero, and render one or more report pages. Provider failures are contained at the dimension level and never block the core report.

**Tech Stack:** Python 3.11+, dataclasses, protocols, pandas, yfinance, Pillow, requests, pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-19-multidimensional-risk-scoring-design.md`

## Global Constraints

- Existing technical rules alone determine candidate inclusion and original candidate ordering.
- New dimensions are informational; no new score or tag may remove a candidate.
- Missing data displays `--` and reduces available points/completeness; it is never scored as zero.
- Display `earned/available`; show normalized `0–100` only when completeness is at least 70%.
- SPY and QQQ fundamentals are `not_applicable`.
- Enrichment has a 60-second total deadline and at most four workers.
- Free providers ship first; provider interfaces remain replaceable.
- No automatic trading, contract recommendation, LLM news inference, or historical IV Rank.
- News keyword matches create at most `caution`, never `high`.
- Enterprise WeChat image payloads remain under 2 MB; paginate when required.

## Review Focus

- All enrichment providers timing out together must still produce and deliver the original technical report; pinned in Task 6.
- A candidate with unavailable fundamentals/options/news must not receive artificial zeroes or a misleading normalized score; pinned in Tasks 2 and 4.
- SPY/QQQ `not_applicable` fundamentals must not lower completeness; pinned in Task 4.
- Missing or one-sided options quotes must create a clear risk tag without recommending a contract; pinned in Tasks 3 and 4.
- Nine expanded candidate cards must paginate under WeCom's 2 MB limit while preserving order; pinned in Task 5.

---

### Task 1: Standard assessment models and configuration

**Files:**
- Modify: `src/market_scanner/models.py`
- Modify: `src/market_scanner/config.py`
- Test: `tests/test_config.py`
- Create: `tests/test_assessment_models.py`

**Interfaces:**
- Produces: `DimensionStatus`, `RiskLevel`, `Evidence`, `RiskTag`, `ProviderResult`, `EnrichmentBundle`, `DimensionScore`, `CandidateAssessment`.
- Produces settings: `earnings_warning_days=3`, `option_expiry_min_days=14`, `option_expiry_max_days=45`, `option_max_spread_ratio=0.10`, `option_min_volume=100`, `option_min_open_interest=500`, `enrichment_timeout_seconds=60`, `provider_timeout_seconds=10`, `enrichment_workers=4`, `normalized_score_min_completeness=0.70`.

- [ ] **Step 1: Write failing model and defaults tests**

Assert frozen model construction, enum values `ok/partial/unavailable/not_applicable/error`, risk levels `info/caution/high`, and all exact settings defaults above.

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m pytest tests/test_assessment_models.py tests/test_config.py -q`
Expected: FAIL because assessment models/settings do not exist.

- [ ] **Step 3: Implement the immutable models and settings**

Use tuples for evidence/tags/dimensions. `CandidateAssessment` carries the original `Candidate`, `earned_points`, `available_points`, `completeness`, optional `normalized_score`, dimensions, and tags.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `python -m pytest tests/test_assessment_models.py tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/market_scanner/models.py src/market_scanner/config.py tests/test_assessment_models.py tests/test_config.py
git commit -m "feat: add multidimensional assessment models"
```

### Task 2: Provider protocols, deadline runner, and free market/fundamental providers

**Files:**
- Create: `src/market_scanner/enrichment.py`
- Create: `src/market_scanner/providers.py`
- Modify: `src/market_scanner/data.py`
- Create: `tests/test_enrichment.py`
- Create: `tests/test_providers.py`

**Interfaces:**
- Consumes: Task 1 statuses/evidence/settings.
- Produces protocols `MarketContextProvider.assess(symbol, bars, benchmarks)`, `FundamentalsProvider.assess(symbol)`, `EventNewsProvider.assess(symbol, now)`, `OptionsProvider.assess(symbol, spot, now)` returning provider result dataclasses.
- Produces `EnrichmentRunner.enrich(candidate_inputs, deadline_seconds) -> dict[str, EnrichmentBundle]`.
- Produces `YahooMarketContextProvider` and `YahooFundamentalsProvider`.

- [ ] **Step 1: Write failing protocol and runner tests**

Test successful aggregation, per-provider exception isolation, four-worker cap, one shared 60-second deadline, cancellation after deadline, ticker reuse, and unavailable results rather than raised exceptions.

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m pytest tests/test_enrichment.py tests/test_providers.py -q`
Expected: FAIL because provider interfaces and runner do not exist.

- [ ] **Step 3: Implement protocols and deadline runner**

Use `ThreadPoolExecutor(max_workers=settings.enrichment_workers)`. Capture exceptions as provider results with `DimensionStatus.ERROR`; do not expose raw credentials or URLs in details.

- [ ] **Step 4: Implement market and fundamental free providers**

Market provider calculates SPY/QQQ trend, 20-session relative returns, and six-month volatility percentile from already-fetched bars. Fundamentals prefer latest quarterly YoY values, fall back to trailing annual values, retain source period, and return `NOT_APPLICABLE` for SPY/QQQ.

- [ ] **Step 5: Run tests to verify GREEN**

Run: `python -m pytest tests/test_enrichment.py tests/test_providers.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/market_scanner/enrichment.py src/market_scanner/providers.py src/market_scanner/data.py tests/test_enrichment.py tests/test_providers.py
git commit -m "feat: add resilient enrichment providers"
```

### Task 3: Event/news and options providers with local macro fallback

**Files:**
- Create: `src/market_scanner/event_news.py`
- Create: `src/market_scanner/options.py`
- Create: `data/macro_events.json`
- Create: `tests/test_event_news.py`
- Create: `tests/test_options.py`

**Interfaces:**
- Consumes: Task 2 provider protocols.
- Produces `YahooEventNewsProvider` and `YahooOptionsProvider`.
- Produces `MacroCalendar.load_online_or_local(now) -> MacroCalendarResult` with local `valid_through` and staleness state.

- [ ] **Step 1: Write failing event/news tests**

Cover 3-day earnings high-risk evidence, 7-day clean window, online macro success, online failure with local fallback, stale local calendar warning, headline deduplication, and conservative negative-keyword `caution` only.

- [ ] **Step 2: Write failing options tests**

Cover nearest expiry within 14–45 days, nearest-ATM call and put, worse-side spread/liquidity, average IV, missing one side, crossed/zero quotes, spread thresholds, and no contract recommendation field.

- [ ] **Step 3: Run tests to verify RED**

Run: `python -m pytest tests/test_event_news.py tests/test_options.py -q`
Expected: FAIL because providers do not exist.

- [ ] **Step 4: Implement event/news provider and macro fallback**

Use `MACRO_CALENDAR_URL` when configured; otherwise default to `https://nfs.faireconomy.media/ff_calendar_thisweek.json`. The request uses a 10-second timeout and falls back to versioned local JSON. A stale fallback returns caution evidence, never “no macro risk.” Store title, publisher, URL, and published time; keyword classification cannot emit high risk.

- [ ] **Step 5: Implement options provider**

Select nearest eligible expiry, nearest-ATM call and put, use worse side for spread/volume/open interest, average valid IVs, and label only impossible/bad IV as abnormal. Do not calculate IV Rank.

- [ ] **Step 6: Run tests to verify GREEN**

Run: `python -m pytest tests/test_event_news.py tests/test_options.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/market_scanner/event_news.py src/market_scanner/options.py data/macro_events.json tests/test_event_news.py tests/test_options.py
git commit -m "feat: add event and options risk evidence"
```

### Task 4: Deterministic scoring and risk-tag policy

**Files:**
- Create: `src/market_scanner/scoring.py`
- Create: `tests/test_scoring.py`

**Interfaces:**
- Consumes: Task 1 models, Task 2/3 provider results, existing `Candidate`.
- Produces `AssessmentScorer.score(candidate, bundle) -> CandidateAssessment`.

- [ ] **Step 1: Write failing scoring tests**

Assert exact maximums `30/20/20/15/15`, weights from the spec, `earned/available`, completeness, normalized score only at completeness `>=0.70`, no zero penalty for unavailable data, `NOT_APPLICABLE` excluded from denominator, tag priority `high > caution > info`, tag deduplication, and original candidate identity preserved.

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m pytest tests/test_scoring.py -q`
Expected: FAIL because scorer does not exist.

- [ ] **Step 3: Implement deterministic scorer**

Each metric contributes its fixed weight only when available. `normalized_score = round(100 * earned_points / available_points)` only when `available_points / applicable_max_points >= 0.70`; otherwise `None`.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `python -m pytest tests/test_scoring.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/market_scanner/scoring.py tests/test_scoring.py
git commit -m "feat: score candidate quality and risk"
```

### Task 5: Paginated image and Markdown reports

**Files:**
- Modify: `src/market_scanner/report.py`
- Modify: `src/market_scanner/image_report.py`
- Modify: `tests/test_report.py`
- Modify: `tests/test_image_report.py`

**Interfaces:**
- Consumes: tuple of `CandidateAssessment` from Task 4.
- Produces `render_png_pages(report) -> tuple[bytes, ...]`; retains `render_png(report) -> bytes` only as compatibility wrapper for single-page tests.
- Produces Markdown with dimensions, tags, evidence, completeness, and observation-score disclaimer.

- [ ] **Step 1: Write failing Markdown and image tests**

Assert `earned/available`, conditional normalized score, five dimensions, max three ordered tags, one evidence line, `--` for missing, completeness disclaimer, original order, nine-card pagination, every PNG width 860, and every page under 2 MB.

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m pytest tests/test_report.py tests/test_image_report.py -q`
Expected: FAIL because enriched rendering/pagination does not exist.

- [ ] **Step 3: Implement compact card layout and pagination**

Render a summary header on every page, cap cards per page based on measured height, and preserve original order. Risk labels and key evidence must remain readable on a phone.

- [ ] **Step 4: Implement Markdown parity**

Use the same formatted assessment values and disclaimer as the image report; preserve existing chunk size behavior.

- [ ] **Step 5: Run tests to verify GREEN**

Run: `python -m pytest tests/test_report.py tests/test_image_report.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/market_scanner/report.py src/market_scanner/image_report.py tests/test_report.py tests/test_image_report.py
git commit -m "feat: render multidimensional risk reports"
```

### Task 6: Integrate enrichment without changing candidate selection

**Files:**
- Modify: `src/market_scanner/main.py`
- Modify: `src/market_scanner/report.py`
- Modify: `tests/test_main.py`
- Modify: `tests/test_report.py`

**Interfaces:**
- Consumes: Tasks 2–5 runner, providers, scorer, paginated renderer.
- Produces extended `Dependencies` with enrichment/scorer and `RunResult.enrichment_failure_count`.

- [ ] **Step 1: Write failing integration tests**

Assert candidate symbols/order match the pre-enrichment result, providers receive only candidates, full provider failure still sends original technical report, timeout still sends, multiple pages call `send_image` in order, enrichment failures are counted separately, and core data failure semantics remain unchanged.

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m pytest tests/test_main.py tests/test_report.py -q`
Expected: FAIL because main does not enrich or paginate.

- [ ] **Step 3: Integrate enrichment and assessment**

Cache daily bars gathered during core scanning, enrich only candidates, preserve ranked candidate order, score results, and build enriched `ScanReport`.

- [ ] **Step 4: Integrate multi-page delivery and failure accounting**

Call `send_image` once per page. Provider errors increment `enrichment_failure_count` but never change a successful run to `DATA_FAILED` or `DELIVERY_FAILED`.

- [ ] **Step 5: Run tests to verify GREEN**

Run: `python -m pytest tests/test_main.py tests/test_report.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/market_scanner/main.py src/market_scanner/report.py tests/test_main.py tests/test_report.py
git commit -m "feat: enrich candidates without blocking delivery"
```

### Task 7: Documentation, full verification, and cloud delivery

**Files:**
- Modify: `README.md`
- Modify: `.github/workflows/premarket-scan.yml` only if dependencies/runtime commands changed.
- Modify: `tests/test_workflow.py` only if workflow changes.

**Interfaces:**
- Consumes: complete feature.
- Produces: documented behavior and a verified main-branch cloud run.

- [ ] **Step 1: Update README**

Document five dimensions, `earned/available`, 70% normalized threshold, tag meanings, missing-data behavior, free-data limitations, macro fallback freshness, multi-image delivery, and non-predictive disclaimer.

- [ ] **Step 2: Run full local verification**

Run: `python -m pytest -q`
Expected: all tests pass with zero failures.

- [ ] **Step 3: Run repository checks**

Run: `git diff --check`
Expected: no output and exit 0.

- [ ] **Step 4: Commit documentation/workflow changes**

```bash
git add README.md .github/workflows/premarket-scan.yml tests/test_workflow.py
git commit -m "docs: explain multidimensional risk scoring"
```

- [ ] **Step 5: Request whole-branch code review and address findings**

Reviewer must verify candidate preservation, missing-data math, deadline containment, options aggregation, tag severity, pagination, and secret hygiene.

- [ ] **Step 6: Push to GitHub main and run send-enabled workflow**

Expected cloud evidence: checkout, dependency install, complete test suite, and `Scheduled or explicitly requested send` all conclude `success`.

- [ ] **Step 7: Verify Enterprise WeChat delivery**

Confirm the cloud step completed successfully and ask the user only if visual receipt cannot be verified from available evidence.
