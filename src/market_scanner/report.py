from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib

import requests

from .models import Candidate, CandidateAssessment, MarketSession


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
    assessments: tuple[CandidateAssessment, ...] = ()
    total_candidate_count: int | None = None


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


def _assessment_lines(assessment: CandidateAssessment) -> list[str]:
    normalized = f"｜观察分 {assessment.normalized_score}/100" if assessment.normalized_score is not None else "｜观察分 --"
    dimensions = " · ".join(
        f"{item.name} {item.earned_points}/{item.available_points}" if item.available_points else f"{item.name} {'不适用' if item.status.value == 'not_applicable' else '--'}"
        for item in assessment.dimensions
    )
    tags = "；".join(f"{tag.level.value}:{tag.title}（{tag.detail}）" for tag in assessment.tags[:3]) or "无突出风险标签"
    evidence = next((item.display for dimension in assessment.dimensions for item in dimension.evidence if item.value is not None), "暂无可用补充依据")
    return [
        f"- 维度得分 `{assessment.earned_points}/{assessment.available_points}`{normalized}｜数据完整度 {assessment.completeness:.0%}",
        f"- {dimensions}",
        f"- 风险：{tags}",
        f"- 依据：{evidence}",
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
    assessment_by_symbol = {
        assessment.candidate.signal.symbol: assessment
        for assessment in report.assessments
        if assessment.candidate is not None
    }
    for item in report.candidates:
        body.extend(_candidate_lines(item))
        assessment = assessment_by_symbol.get(item.signal.symbol)
        if assessment:
            body.extend(_assessment_lines(assessment))
    if report.failures:
        body.append(f"> 数据异常标的：{', '.join(report.failures)}")
    body.append("> 观察分基于当前可用数据，不代表胜率或涨跌预测。")
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
        self._post({"msgtype": "markdown", "markdown": {"content": markdown}})

    def send_image(self, image_bytes: bytes) -> None:
        if len(image_bytes) > 2 * 1024 * 1024:
            raise ReportError("enterprise WeChat image exceeds 2 MB")
        self._post(
            {
                "msgtype": "image",
                "image": {
                    "base64": base64.b64encode(image_bytes).decode("ascii"),
                    "md5": hashlib.md5(image_bytes).hexdigest(),
                },
            }
        )

    def _post(self, payload: dict) -> None:
        try:
            response = self._session.post(
                self._webhook_url,
                json=payload,
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise ReportError("enterprise WeChat webhook request failed") from None
        if payload.get("errcode") != 0:
            raise ReportError(f"enterprise WeChat returned errcode {payload.get('errcode')}")
