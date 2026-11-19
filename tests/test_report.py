import base64
import hashlib
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from market_scanner.models import Candidate, CandidateAssessment, DimensionScore, DimensionStatus, MarketSession, PremarketQuote, QuoteStatus, RiskLevel, RiskTag, TrendSignal
from market_scanner.report import ReportError, ScanReport, WeComClient, render_markdown


def candidate(symbol="AAPL"):
    signal = TrendSignal(symbol, date(2026, 11, 18), 100, 95, 90, 4, ("平台突破",), 92)
    quote = PremarketQuote(symbol, QuoteStatus.OK, 101, datetime(2026, 11, 19, 8, 30, tzinfo=ZoneInfo("America/New_York")))
    return Candidate(signal, quote, 0.01, "允许关注")


def report(items=None, failures=()):
    session = MarketSession(date(2026, 11, 19), datetime(2026, 11, 19, 9, 30, tzinfo=ZoneInfo("America/New_York")))
    return ScanReport(session, "SPY 合格", "QQQ 合格", tuple(items or ()), tuple(failures))


def test_render_candidate_and_no_candidate_reports():
    text = render_markdown(report([candidate()]))[0]
    assert all(value in text for value in ["2026-11-19", "09:30", "AAPL", "平台突破", "101.00", "95.00", "90.00", "92.00", "仅供研究"])

    empty = render_markdown(report(failures=("TSLA",)))[0]
    assert "今日无符合条件标的" in empty
    assert "TSLA" in empty


def test_long_report_is_split_and_each_chunk_has_title():
    chunks = render_markdown(report([candidate(f"SYM{i:03}") for i in range(120)]), max_chars=1200)
    assert len(chunks) > 1
    assert all(chunk.startswith("# 美股盘前趋势扫描") for chunk in chunks)
    assert all(len(chunk) <= 1200 for chunk in chunks)


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {"errcode": 0}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error:
            raise self.error
        return self.response


def test_wecom_success_and_business_error_redacts_secret():
    url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=secret-value"
    WeComClient(url, session=FakeSession(FakeResponse())).send("hello")

    client = WeComClient(url, session=FakeSession(FakeResponse(payload={"errcode": 93000, "errmsg": "bad"})))
    with pytest.raises(ReportError) as exc:
        client.send("hello")
    assert "93000" in str(exc.value)
    assert "secret-value" not in str(exc.value)


def test_wecom_http_or_network_error_is_report_error():
    url = "https://example.invalid/?key=secret"
    with pytest.raises(ReportError):
        WeComClient(url, session=FakeSession(FakeResponse(status=500))).send("hello")
    with pytest.raises(ReportError) as exc:
        WeComClient(url, session=FakeSession(error=TimeoutError("url secret"))).send("hello")
    assert "secret" not in str(exc.value)


def test_stale_quote_does_not_render_numeric_price():
    item = candidate()
    stale = Candidate(item.signal, PremarketQuote("AAPL", QuoteStatus.STALE, 99, item.quote.observed_at), None, "数据异常")
    text = render_markdown(report([stale]))[0]
    assert "盘前 `--`" in text
    assert "盘前 `99.00`" not in text


def test_enriched_markdown_shows_scores_completeness_tags_and_disclaimer():
    item = candidate()
    assessment = CandidateAssessment(
        item, 62, 80, 0.8, 78,
        (DimensionScore("技术", 26, 30, DimensionStatus.OK), DimensionScore("期权", 8, 15, DimensionStatus.PARTIAL)),
        (RiskTag(RiskLevel.CAUTION, "spread", "期权价差偏大", "12%"),),
    )
    enriched = ScanReport(report().session, "SPY 趋势合格", "QQQ 趋势合格", (item,), assessments=(assessment,))

    text = "\n".join(render_markdown(enriched))

    assert "62/80" in text
    assert "观察分 78/100" in text
    assert "数据完整度 80%" in text
    assert "技术 26/30" in text and "期权 8/15" in text
    assert "期权价差偏大" in text
    assert "不代表胜率" in text


def test_formatted_traceback_does_not_contain_webhook_key():
    import traceback

    url = "https://example.invalid/?key=traceback-secret"
    try:
        WeComClient(url, session=FakeSession(error=RuntimeError(url))).send("hello")
    except ReportError as exc:
        rendered = "".join(traceback.format_exception(exc))
    assert "traceback-secret" not in rendered


def test_wecom_image_payload_contains_original_bytes_and_md5():
    image_bytes = b"\x89PNG\r\n\x1a\nreal-image"
    session = FakeSession(FakeResponse())

    WeComClient("https://example.invalid/?key=secret", session=session).send_image(image_bytes)

    payload = session.calls[0][1]["json"]
    assert payload["msgtype"] == "image"
    assert base64.b64decode(payload["image"]["base64"]) == image_bytes
    assert payload["image"]["md5"] == hashlib.md5(image_bytes).hexdigest()


def test_wecom_image_over_two_megabytes_fails_before_http_request():
    session = FakeSession(FakeResponse())
    client = WeComClient("https://example.invalid/?key=secret", session=session)

    with pytest.raises(ReportError, match="2 MB"):
        client.send_image(b"x" * (2 * 1024 * 1024 + 1))

    assert session.calls == []


def test_wecom_image_failure_redacts_secret():
    url = "https://example.invalid/?key=image-secret"
    session = FakeSession(FakeResponse(payload={"errcode": 93000, "errmsg": url}))

    with pytest.raises(ReportError) as exc:
        WeComClient(url, session=session).send_image(b"png")

    assert "93000" in str(exc.value)
    assert "image-secret" not in str(exc.value)
