from datetime import date, datetime
from io import BytesIO
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

from market_scanner.image_report import _candidate_view, _status_style, render_png, render_png_pages, resolve_font_path
from market_scanner.models import Candidate, CandidateAssessment, DimensionScore, DimensionStatus, MarketSession, PremarketQuote, QuoteStatus, RiskLevel, RiskTag, TrendSignal
from market_scanner.report import ReportError, ScanReport


NY = ZoneInfo("America/New_York")
FONT_PATH = r"C:\Windows\Fonts\msyh.ttc"


def make_candidate(*, status=QuoteStatus.OK, price=101.0):
    signal = TrendSignal("AAPL", date(2026, 11, 18), 100, 95, 90, 4, ("平台突破",), 92)
    quote = PremarketQuote("AAPL", status, price, datetime(2026, 11, 19, 8, 30, tzinfo=NY))
    change = 0.01 if status == QuoteStatus.OK else None
    label = "允许关注" if status == QuoteStatus.OK else "数据异常"
    return Candidate(signal, quote, change, label)


def make_report(items=(), failures=()):
    session = MarketSession(date(2026, 11, 19), datetime(2026, 11, 19, 9, 30, tzinfo=NY))
    return ScanReport(session, "SPY 合格", "QQQ 合格", tuple(items), tuple(failures))


@pytest.mark.parametrize("items", [(), (make_candidate(),)])
def test_render_png_is_valid_860_pixel_image_for_empty_or_candidate_report(items):
    payload = render_png(make_report(items), font_path=FONT_PATH)

    assert payload.startswith(b"\x89PNG\r\n\x1a\n")
    image = Image.open(BytesIO(payload))
    assert image.format == "PNG"
    assert image.width == 860
    assert image.height >= 600


def test_candidate_view_hides_numeric_price_for_stale_quote():
    view = _candidate_view(make_candidate(status=QuoteStatus.STALE, price=99.0))

    assert view.quote_price == "--"
    assert "99.00" not in view.quote_price


def test_candidate_view_exposes_ma20_reference_range():
    view = _candidate_view(make_candidate())

    assert view.reference_range == "93.10–96.90"


def test_invalid_or_anomalous_status_is_never_green():
    assert _status_style("允许关注")[0] == "#07855d"
    assert _status_style("信号失效")[0] == "#c64242"
    assert _status_style("数据异常")[0] == "#c64242"
    assert _status_style("跳空偏高不追")[0] == "#bd7000"


def test_resolve_font_path_raises_clear_error_when_no_font_exists(monkeypatch):
    monkeypatch.delenv("SCANNER_FONT_PATH", raising=False)
    monkeypatch.setattr("market_scanner.image_report._FONT_CANDIDATES", ())

    with pytest.raises(ReportError, match="CJK font"):
        resolve_font_path()


def test_font_resolution_skips_existing_invalid_or_non_cjk_files(monkeypatch, tmp_path):
    valid_font = resolve_font_path()
    invalid = tmp_path / "not-a-font.ttf"
    invalid.write_text("not a font", encoding="utf-8")
    monkeypatch.delenv("SCANNER_FONT_PATH", raising=False)
    monkeypatch.setattr(
        "market_scanner.image_report._FONT_CANDIDATES",
        (str(invalid), r"C:\Windows\Fonts\arial.ttf", valid_font),
    )

    assert resolve_font_path() == valid_font


def test_enriched_image_report_paginates_nine_cards_and_preserves_order():
    items = tuple(make_candidate(price=101 + index) for index in range(9))
    assessments = tuple(
        CandidateAssessment(
            item, 60 + index, 80, 0.8, 75 + index,
            (DimensionScore("技术", 26, 30, DimensionStatus.OK),),
            (RiskTag(RiskLevel.CAUTION, f"tag-{index}", "风险标签", "说明"),),
        )
        for index, item in enumerate(items)
    )
    enriched = ScanReport(
        MarketSession(date(2026, 11, 19), datetime(2026, 11, 19, 9, 30, tzinfo=NY)),
        "SPY合格", "QQQ合格", items, assessments=assessments,
    )

    pages = render_png_pages(enriched, font_path=FONT_PATH)

    assert len(pages) >= 2
    assert all(page.startswith(b"\x89PNG") and len(page) < 2 * 1024 * 1024 for page in pages)
    assert all(Image.open(BytesIO(page)).width == 860 for page in pages)
