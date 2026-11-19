# Enterprise WeChat Image Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the confirmed “清晰摘要” premarket report as a PNG and deliver it through the Enterprise WeChat robot image endpoint.

**Architecture:** A focused Pillow renderer converts `ScanReport` into PNG bytes and owns layout/font selection. `WeComClient` owns the image transport contract (size validation, Base64, MD5), while `run_scan` keeps Markdown for dry runs and uses the PNG path only for sends.

**Tech Stack:** Python 3.11+, Pillow, requests, pytest, GitHub Actions

**Spec:** `docs/superpowers/specs/2026-11-19-wecom-image-report.md`

## Global Constraints

- Render locally with Pillow; do not depend on a browser or external image service.
- Keep the Webhook exclusively in `WECOM_WEBHOOK_URL`; never persist or print it.
- Keep `--dry-run` as Markdown output and change only `--send` to PNG delivery.
- Reject image payloads larger than 2 MB before network delivery.
- Support Windows Microsoft YaHei and Linux Noto Sans CJK, with `SCANNER_FONT_PATH` taking precedence.

## Review Focus

- A missing CJK font must produce a clear, secret-free `ReportError`, not a corrupt or blank image.
- A stale or missing premarket quote must render `--`, never a misleading numeric value.
- An empty candidate list must still produce a valid, readable PNG.
- A PNG over 2 MB must fail before making an HTTP request.
- A nonzero WeCom business error or network exception must not expose the Webhook key.

---

### Task 1: PNG report renderer

**Files:**
- Create: `src/market_scanner/image_report.py`
- Create: `tests/test_image_report.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: `market_scanner.report.ScanReport` and model fields already used by `render_markdown`.
- Produces: `render_png(report: ScanReport, *, font_path: str | None = None) -> bytes`, `resolve_font_path(explicit: str | None = None) -> str`, and internal `_candidate_view(item: Candidate) -> CandidateView` used by the renderer.

- [ ] **Step 1: Write failing renderer tests**

Add tests that assert `render_png` begins with the PNG signature, produces a nontrivial image with width 860, handles zero candidates, `_candidate_view` maps a stale quote to `--` instead of its numeric price, and missing-font resolution raises `ReportError`. Use a real test font path and real Pillow image decoding; monkeypatch only the explicit font-candidate list for the missing-font branch.

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m pytest tests/test_image_report.py -q`

Expected: FAIL because `market_scanner.image_report` does not exist.

- [ ] **Step 3: Implement the minimal renderer**

Add Pillow to runtime dependencies. Implement `resolve_font_path(...)`, a small internal presentation-row builder, and `render_png(...)` with the confirmed A layout: navy header, market summary strip, white candidate panels with green/amber status accents, dynamic height, failure footer, and disclaimer.

- [ ] **Step 4: Run renderer tests and full suite**

Run: `python -m pytest tests/test_image_report.py -q && python -m pytest -q`

Expected: all tests PASS with no warnings.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/market_scanner/image_report.py tests/test_image_report.py
git commit -m "feat: render premarket scan as png"
```

### Task 2: Enterprise WeChat image delivery

**Files:**
- Modify: `src/market_scanner/report.py`
- Modify: `tests/test_report.py`

**Interfaces:**
- Consumes: PNG `bytes` from Task 1.
- Produces: `WeComClient.send_image(image_bytes: bytes) -> None`; retains `send(markdown: str) -> None` for compatibility.

- [ ] **Step 1: Write failing transport tests**

Add tests that decode the posted Base64 back to the original literal PNG bytes, compare the posted MD5 with a hand-derived `hashlib.md5` value, verify a payload larger than 2 MB does not call `post`, and verify network/business failures redact the Webhook key.

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m pytest tests/test_report.py -q`

Expected: FAIL because `send_image` is missing.

- [ ] **Step 3: Implement image transport**

Implement `send_image(image_bytes: bytes) -> None` using Enterprise WeChat `msgtype=image`, Base64, lowercase MD5, a 2 MB preflight limit, the existing 10-second timeout, and the existing secret-safe `ReportError` boundary.

- [ ] **Step 4: Run transport tests and full suite**

Run: `python -m pytest tests/test_report.py -q && python -m pytest -q`

Expected: all tests PASS with no warnings.

- [ ] **Step 5: Commit**

```bash
git add src/market_scanner/report.py tests/test_report.py
git commit -m "feat: send png reports to enterprise wechat"
```

### Task 3: Wire image reports into scan execution

**Files:**
- Modify: `src/market_scanner/main.py`
- Modify: `tests/test_main.py`

**Interfaces:**
- Consumes: `render_png(...)` from Task 1 and `WeComClient.send_image(...)` from Task 2.
- Produces: send mode renders once and calls `send_image`; dry-run mode continues calling `render_markdown` and output.

- [ ] **Step 1: Write failing execution tests**

Update the sender fake with an image collection and add assertions that send mode records one PNG beginning with the PNG signature, a partial data failure appears in the rendered report path, dry-run still emits Markdown and never constructs the sender, and renderer/delivery exceptions return `DELIVERY_FAILED`.

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m pytest tests/test_main.py -q`

Expected: FAIL because send mode still calls `send(markdown)`.

- [ ] **Step 3: Implement execution wiring**

Render Markdown only inside the dry-run branch. In send mode call `render_png(report)` once, construct the sender, and call `send_image(image_bytes)` once inside the existing delivery error boundary.

- [ ] **Step 4: Run execution tests and full suite**

Run: `python -m pytest tests/test_main.py -q && python -m pytest -q`

Expected: all tests PASS with no warnings.

- [ ] **Step 5: Commit**

```bash
git add src/market_scanner/main.py tests/test_main.py
git commit -m "feat: deliver scanner results as image"
```

### Task 4: Cloud font provisioning and operating instructions

**Files:**
- Modify: `.github/workflows/premarket-scan.yml`
- Modify: `tests/test_workflow.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: Linux Noto Sans CJK font lookup from Task 1 and existing `WECOM_WEBHOOK_URL` secret wiring.
- Produces: GitHub Actions environment with a discoverable CJK font and documentation for local/cloud image delivery.

- [ ] **Step 1: Write failing workflow behavior test**

Extend the workflow test to load YAML and assert the scan job contains a font-install step before the send step, while retaining scheduled and manual-send behavior and the `WECOM_WEBHOOK_URL` secret environment mapping.

- [ ] **Step 2: Run test to verify RED**

Run: `python -m pytest tests/test_workflow.py -q`

Expected: FAIL because the workflow has no CJK font installation step.

- [ ] **Step 3: Provision font and document operation**

Add an Ubuntu `apt-get install -y fonts-noto-cjk` step. Update README with the A-style image behavior, `SCANNER_FONT_PATH` override, GitHub Secret name, manual dry-run/send commands, and no-candidate behavior.

- [ ] **Step 4: Run workflow tests and full suite**

Run: `python -m pytest tests/test_workflow.py -q && python -m pytest -q`

Expected: all tests PASS with no warnings.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/premarket-scan.yml tests/test_workflow.py README.md
git commit -m "docs: provision image reports in github actions"
```

### Task 5: End-to-end local verification

**Files:**
- Modify only if verification reveals a tested defect in files owned by Tasks 1-4.

**Interfaces:**
- Consumes: complete image render, delivery payload, scan wiring, and workflow configuration.
- Produces: fresh verification evidence and one local A-style PNG preview; no production Webhook is persisted.

- [ ] **Step 1: Run the complete test suite**

Run: `python -m pytest -q`

Expected: all tests PASS with no warnings.

- [ ] **Step 2: Generate and inspect a local sample PNG**

Run a repository-local verification script or one-off command that constructs a representative `ScanReport`, calls `render_png`, writes the returned bytes to the plan workspace, and checks the decoded format, dimensions, and size under 2 MB.

- [ ] **Step 3: Verify repository hygiene**

Run: `git status --short && git grep -n "qyapi.weixin.qq.com/cgi-bin/webhook/send?key=" -- . ':!docs/superpowers/plans/*'`

Expected: only intended tracked changes, and no Webhook URL or key in tracked source.

- [ ] **Step 4: Commit any verification-only documentation changes**

If no tracked changes were needed, record the verification result in the execution ledger without an empty commit.
