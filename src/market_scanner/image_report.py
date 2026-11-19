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
        invalidation=f"{item.signal.invalidation:.2f}",
    )


def resolve_font_path(explicit: str | None = None) -> str:
    candidates = (explicit, os.getenv("SCANNER_FONT_PATH"), *_FONT_CANDIDATES)
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    raise ReportError("a CJK font is required; set SCANNER_FONT_PATH")


def _font(path: str, size: int, *, index: int = 0) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size=size, index=index)


def _text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], value: str, font, fill: str) -> None:
    draw.text(xy, value, font=font, fill=fill)


def render_png(report: ScanReport, *, font_path: str | None = None) -> bytes:
    path = resolve_font_path(font_path)
    candidates = tuple(_candidate_view(item) for item in report.candidates)
    content_height = max(300, len(candidates) * 220)
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
    draw.ellipse((690, 52, 708, 70), fill="#43d09a")
    _text(draw, (720, 45), "市场正常", regular_20, "#b8f0dc")

    draw.rounded_rectangle((36, 260, 824, 335), radius=24, fill="#ffffff")
    summaries = (("SPY", report.spy_summary), ("QQQ", report.qqq_summary), ("入选", str(len(candidates))))
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
            warning = any(word in item.status for word in ("不", "等待", "异常"))
            accent = "#bd7000" if warning else "#07855d"
            soft = "#fff1d8" if warning else "#e6f6ef"
            draw.rounded_rectangle((36, y, 824, y + 200), radius=24, fill="#ffffff")
            draw.rounded_rectangle((36, y, 46, y + 200), radius=5, fill=accent)
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
            _text(draw, (76, y + 140), "MA20", regular_20, "#687690")
            _text(draw, (145, y + 140), item.ma20, regular_24, "#142a4b")
            _text(draw, (315, y + 140), "参考失效位", regular_20, "#687690")
            _text(draw, (450, y + 140), item.invalidation, regular_24, "#142a4b")
            y += 220

    if report.failures:
        draw.rounded_rectangle((36, y, 824, y + 66), radius=18, fill="#fff0f0")
        _text(draw, (60, y + 20), f"数据异常：{', '.join(report.failures)}", regular_20, "#b23b3b")
        y += 86

    _text(draw, (38, height - 74), "顺日线趋势 · 不预测涨跌", regular_20, "#687690")
    _text(draw, (510, height - 74), "仅供策略筛选，不构成投资建议", regular_20, "#687690")

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
