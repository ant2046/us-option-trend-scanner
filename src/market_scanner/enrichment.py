from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from queue import Empty, Queue
from threading import Thread
from time import monotonic
from typing import Mapping

import pandas as pd

from .config import Settings
from .models import DimensionStatus, EnrichmentBundle, Evidence, ProviderResult


@dataclass(frozen=True)
class CandidateInput:
    symbol: str
    candidate: object
    bars: pd.DataFrame
    benchmarks: Mapping[str, pd.DataFrame]
    spot: float | None
    now: datetime


class EnrichmentRunner:
    def __init__(self, market, fundamental, event_news, options, settings: Settings | None = None):
        self.providers = {
            "market": market,
            "fundamental": fundamental,
            "event_news": event_news,
            "options": options,
        }
        self.settings = settings or Settings()

    @staticmethod
    def _error_result(dimension: str) -> ProviderResult:
        return ProviderResult(
            dimension,
            DimensionStatus.ERROR,
            (Evidence("provider_error", None, "数据源暂不可用", dimension),),
        )

    def _invoke(self, dimension: str, context: CandidateInput) -> ProviderResult:
        provider = self.providers[dimension]
        if dimension == "market":
            return provider.assess(context.symbol, context.bars, context.benchmarks)
        if dimension == "fundamental":
            return provider.assess(context.symbol)
        if dimension == "event_news":
            return provider.assess(context.symbol, context.now)
        return provider.assess(context.symbol, context.spot, context.now)

    def _call(self, dimension: str, context: CandidateInput) -> ProviderResult:
        for attempt in range(self.settings.provider_retries + 1):
            outcome = Queue(maxsize=1)
            def invoke():
                try:
                    outcome.put((True, self._invoke(dimension, context)))
                except Exception:
                    outcome.put((False, None))
            Thread(target=invoke, daemon=True).start()
            try:
                ok, result = outcome.get(timeout=self.settings.provider_timeout_seconds)
            except Empty:
                return self._error_result(dimension)
            if ok:
                return result
            if attempt == self.settings.provider_retries:
                break
        return self._error_result(dimension)

    def enrich(self, contexts: tuple[CandidateInput, ...]) -> dict[str, EnrichmentBundle]:
        values: dict[str, dict[str, ProviderResult]] = {item.symbol: {} for item in contexts}
        tasks = Queue()
        results = Queue()
        for item in contexts:
            for dimension in self.providers:
                tasks.put((dimension, item))

        def worker():
            while True:
                try:
                    dimension, item = tasks.get_nowait()
                except Empty:
                    return
                results.put((item.symbol, dimension, self._call(dimension, item)))

        remaining = tasks.qsize()
        workers = min(self.settings.enrichment_workers, remaining)
        for _ in range(workers):
            Thread(target=worker, daemon=True).start()
        deadline = monotonic() + self.settings.enrichment_timeout_seconds
        while remaining and monotonic() < deadline:
            try:
                symbol, dimension, result = results.get(timeout=max(0, min(0.05, deadline - monotonic())))
            except Empty:
                continue
            values[symbol][dimension] = result
            remaining -= 1
        for symbol, parts in values.items():
            for dimension in self.providers:
                parts.setdefault(dimension, self._error_result(dimension))
        return {
            symbol: EnrichmentBundle(
                market=parts.get("market"),
                fundamental=parts.get("fundamental"),
                event_news=parts.get("event_news"),
                options=parts.get("options"),
            )
            for symbol, parts in values.items()
        }
