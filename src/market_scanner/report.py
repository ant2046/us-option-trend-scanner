from __future__ import annotations

from dataclasses import dataclass

import requests

from .models import Candidate, MarketSession


TITLE = "# 美股盘前趋势扫描"
DISCLAIMER = "> 仅供研究，不构成投资建议；系统不会自动下单。"


class ReportError(RuntimeError):
    """Raised when rendering or delivering a report fails."""


@dataclass(frozen=True)
class ScanReport:
    session: MarketSession
    spy_summary: str
    qqq_summary: str
    candidates: tuple[Candidate, ...]
    failures: tuple[str, ...] = ()


def _candidate_lines(item: Candidate) -> list[str]:
    signal = item.signal
    quote_price = (
        f"{item.quote.price:.2f}"
        if item.quote.status.value == "ok" and item.quote.price is not None
        else "--"
    )
    change = f"{item.premarket_change:+.2%}" if item.premarket_change is not None else "--"
    return [
        f"## {signal.symbol} · {' / '.join(signal.triggers)} · {signal.score}/4",
        f"- 前收 `{signal.close:.2f}`｜盘前 `{quote_price}`（{change}）｜**{item.status}**",
        f"- MA20 `{signal.ma20:.2f}`｜MA50 `{signal.ma50:.2f}`｜参考失效位 `{signal.invalidation:.2f}`",
    ]


def render_markdown(report: ScanReport, *, max_chars: int = 3800) -> list[str]:
    header = [
        TITLE,
        f"> 交易日：{report.session.session_date.isoformat()}｜预计开盘：{report.session.opens_at:%H:%M}（纽约）",
        f"> 市场：{report.spy_summary}；{report.qqq_summary}",
    ]
    body: list[str] = []
    if not report.candidates:
        body.append("## 今日无符合条件标的")
    for item in report.candidates:
        body.extend(_candidate_lines(item))
    if report.failures:
        body.append(f"> 数据异常标的：{', '.join(report.failures)}")
    body.append(DISCLAIMER)

    chunks: list[str] = []
    current = "\n".join(header)
    for line in body:
        proposed = f"{current}\n{line}"
        if len(proposed) > max_chars and current != "\n".join(header):
            chunks.append(current)
            current = f"{TITLE}\n{line}"
        else:
            current = proposed
    chunks.append(current)
    return chunks


class WeComClient:
    def __init__(self, webhook_url: str, *, session=None):
        self._webhook_url = webhook_url
        self._session = session or requests.Session()

    def send(self, markdown: str) -> None:
        try:
            response = self._session.post(
                self._webhook_url,
                json={"msgtype": "markdown", "markdown": {"content": markdown}},
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise ReportError("enterprise WeChat webhook request failed") from None
        if payload.get("errcode") != 0:
            raise ReportError(f"enterprise WeChat returned errcode {payload.get('errcode')}")
