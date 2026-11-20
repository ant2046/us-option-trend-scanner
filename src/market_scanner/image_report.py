from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .models import Candidate, QuoteStatus
from .report import ReportError, ScanReport


WIDTH = 860
_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
)


@dataclass(frozen=True)
class CandidateView:
    symbol: str
    trigger: str
    status: str
    quote_price: str
    change: str
    close: str
    ma20: str
    reference_range: str
    invalidation: str


def _candidate_view(item: Candidate) -> CandidateView:
    quote_ok = item.quote.status == QuoteStatus.OK and item.quote.price is not None
    return CandidateView(
        symbol=item.signal.symbol,
        trigger=" / ".join(item.signal.triggers),
        status=item.status,
        quote_price=f"{item.quote.price:.2f}" if quote_ok else "--",
        change=f"{item.premarket_change:+.1%}" if quote_ok and item.premarket_change is not None else "--",
        close=f"{item.signal.close:.2f}",
        ma20=f"{item.signal.ma20:.2f}",
        reference_range=f"{item.signal.ma20 * 0.98:.2f}–{item.signal.ma20 * 1.02:.2f}",
        invalidation=f"{item.signal.invalidation:.2f}",
    )


def _font_supports_report_text(path: str) -> bool:
    try:
        font = ImageFont.truetype(path, size=24)
        masks = [bytes(font.getmask(char)) for char in "美股盘前"]
    except (OSError, ValueError):
        return False
    return all(any(mask) for mask in masks) and len(set(masks)) >= 4


def resolve_font_path(explicit: str | None = None) -> str:
    candidates = (explicit, os.getenv("SCANNER_FONT_PATH"), *_FONT_CANDIDATES)
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and _font_supports_report_text(str(candidate)):
            return str(candidate)
    raise ReportError("a CJK font is required; set SCANNER_FONT_PATH")


def _font(path: str, size: int, *, index: int = 0) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size=size, index=index)


def _text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], value: str, font, fill: str) -> None:
    draw.text(xy, value, font=font, fill=fill)


def _status_style(status: str) -> tuple[str, str]:
    if status == "允许关注":
        return "#07855d", "#e6f6ef"
    if "失效" in status or "异常" in status:
        return "#c64242", "#fde8e8"
    return "#bd7000", "#fff1d8"


def render_png(report: ScanReport, *, font_path: str | None = None) -> bytes:
    path = resolve_font_path(font_path)
    candidates = tuple(_candidate_view(item) for item in report.candidates)
    assessment_by_symbol = {
        assessment.candidate.signal.symbol: assessment
        for assessment in report.assessments
        if assessment.candidate is not None
    }
    card_height = 315 if assessment_by_symbol else 200
    card_step = card_height + 20
    content_height = max(300, len(candidates) * card_step)
    height = 360 + content_height + (90 if report.failures else 0) + 110
    image = Image.new("RGB", (WIDTH, height), "#f4f7fb")
    draw = ImageDraw.Draw(image)

    regular_20 = _font(path, 20)
    regular_24 = _font(path, 24)
    regular_28 = _font(path, 28)
    regular_38 = _font(path, 38)
    bold_24 = _font(path, 24, index=0)
    bold_34 = _font(path, 34, index=0)

    draw.rounded_rectangle((0, 0, WIDTH, 235), radius=28, fill="#17345b")
    _text(draw, (48, 45), "PRE-MARKET SCAN", regular_20, "#85a8d8")
    _text(draw, (48, 85), "美股盘前趋势扫描", regular_38, "#ffffff")
    _text(
        draw,
        (48, 145),
        f"{report.session.session_date.isoformat()} · 预计开盘 {report.session.opens_at:%H:%M}（纽约）",
        regular_20,
        "#c0d1e9",
    )
    if len(report.failures) >= 9:
        market_label, market_color = "数据不可用", "#ffadad"
    elif report.failures:
        market_label, market_color = "部分数据异常", "#ffd38a"
    else:
        market_label, market_color = "市场正常", "#b8f0dc"
    draw.ellipse((650, 52, 668, 70), fill=market_color)
    _text(draw, (680, 45), market_label, regular_20, market_color)

    draw.rounded_rectangle((36, 260, 824, 335), radius=24, fill="#ffffff")
    summaries = (("SPY", report.spy_summary), ("QQQ", report.qqq_summary), ("入选", str(report.total_candidate_count if report.total_candidate_count is not None else len(candidates))))
    for index, (label, value) in enumerate(summaries):
        left = 36 + index * 263
        if index:
            draw.line((left, 274, left, 321), fill="#e2e8f1", width=2)
        _text(draw, (left + 35, 283), label, bold_24, "#142a4b")
        color = "#07855d" if "合格" in value else "#687690"
        _text(draw, (left + 105, 285), value, regular_20, color)

    y = 365
    if not candidates:
        draw.rounded_rectangle((36, y, 824, y + 210), radius=24, fill="#ffffff")
        _text(draw, (230, y + 70), "今日无符合条件标的", regular_28, "#142a4b")
        _text(draw, (205, y + 120), "保持耐心，不为交易而交易", regular_20, "#687690")
        y += 230
    else:
        for item in candidates:
            accent, soft = _status_style(item.status)
            draw.rounded_rectangle((36, y, 824, y + card_height), radius=24, fill="#ffffff")
            draw.rounded_rectangle((36, y, 46, y + card_height), radius=5, fill=accent)
            _text(draw, (76, y + 28), item.symbol, bold_34, "#0e2a50")
            _text(draw, (225, y + 39), item.trigger, regular_20, "#687690")
            pill_left = 650
            draw.rounded_rectangle((pill_left, y + 26, 792, y + 70), radius=22, fill=soft)
            _text(draw, (pill_left + 18, y + 35), item.status, regular_20, accent)
            _text(draw, (76, y + 86), "盘前价", regular_20, "#687690")
            _text(draw, (160, y + 86), item.quote_price, regular_24, "#142a4b")
            _text(draw, (315, y + 86), "涨跌", regular_20, "#687690")
            _text(draw, (380, y + 86), item.change, regular_24, accent)
            _text(draw, (525, y + 86), "前收", regular_20, "#687690")
            _text(draw, (590, y + 86), item.close, regular_24, "#142a4b")
            _text(draw, (76, y + 140), "MA20参考区间", regular_20, "#687690")
            _text(draw, (235, y + 140), item.reference_range, regular_24, "#142a4b")
            _text(draw, (515, y + 140), "失效位", regular_20, "#687690")
            _text(draw, (590, y + 140), item.invalidation, regular_24, "#142a4b")
            assessment = assessment_by_symbol.get(item.symbol)
            if assessment:
                total = f"{assessment.earned_points}/{assessment.available_points}"
                normalized = f" · 观察分 {assessment.normalized_score}" if assessment.normalized_score is not None else " · 观察分 --"
                _text(draw, (76, y + 185), f"维度 {total}{normalized} · 完整度 {assessment.completeness:.0%}", regular_20, "#17345b")
                dimension_text = " · ".join(
                    f"{score.name}{score.earned_points}/{score.available_points}" if score.available_points else f"{score.name}{'不适用' if score.status.value == 'not_applicable' else '--'}"
                    for score in assessment.dimensions
                )
                _text(draw, (76, y + 220), dimension_text[:52], regular_20, "#687690")
                tags = " / ".join(f"{tag.title}:{tag.detail}" for tag in assessment.tags[:3]) or "无突出风险标签"
                tag_color = "#c64242" if assessment.tags and assessment.tags[0].level.value == "high" else "#bd7000" if assessment.tags and assessment.tags[0].level.value == "caution" else "#687690"
                _text(draw, (76, y + 250), tags[:36], regular_20, tag_color)
                evidence = next((entry.display for score in assessment.dimensions for entry in score.evidence if entry.value is not None), "暂无可用补充依据")
                _text(draw, (76, y + 282), f"依据：{evidence}"[:44], regular_20, "#687690")
            y += card_step

    if report.failures:
        draw.rounded_rectangle((36, y, 824, y + 66), radius=18, fill="#fff0f0")
        _text(draw, (60, y + 20), f"数据异常：{', '.join(report.failures)}", regular_20, "#b23b3b")
        y += 86

    _text(draw, (38, height - 74), "观察分基于可用数据 · 不代表胜率", regular_20, "#687690")
    _text(draw, (510, height - 74), "仅供策略筛选，不构成投资建议", regular_20, "#687690")

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def render_png_pages(report: ScanReport, *, font_path: str | None = None, cards_per_page: int = 3) -> tuple[bytes, ...]:
    if len(report.candidates) <= cards_per_page:
        return (render_png(report, font_path=font_path),)
    pages = []
    assessment_by_symbol = {
        assessment.candidate.signal.symbol: assessment
        for assessment in report.assessments
        if assessment.candidate is not None
    }
    for start in range(0, len(report.candidates), cards_per_page):
        candidates = report.candidates[start : start + cards_per_page]
        assessments = tuple(
            assessment_by_symbol[item.signal.symbol]
            for item in candidates
            if item.signal.symbol in assessment_by_symbol
        )
        page = ScanReport(
            report.session,
            report.spy_summary,
            report.qqq_summary,
            candidates,
            report.failures,
            assessments,
            report.total_candidate_count if report.total_candidate_count is not None else len(report.candidates),
        )
        payload = render_png(page, font_path=font_path)
        if len(payload) > 2 * 1024 * 1024:
            raise ReportError("enterprise WeChat image exceeds 2 MB")
        pages.append(payload)
    return tuple(pages)
