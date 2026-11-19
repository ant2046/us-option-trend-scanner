from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime
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

    def _call(self, dimension: str, context: CandidateInput) -> ProviderResult:
        provider = self.providers[dimension]
        try:
            if dimension == "market":
                return provider.assess(context.symbol, context.bars, context.benchmarks)
            if dimension == "fundamental":
                return provider.assess(context.symbol)
            if dimension == "event_news":
                return provider.assess(context.symbol, context.now)
            return provider.assess(context.symbol, context.spot, context.now)
        except Exception:
            return self._error_result(dimension)

    def enrich(self, contexts: tuple[CandidateInput, ...]) -> dict[str, EnrichmentBundle]:
        values: dict[str, dict[str, ProviderResult]] = {item.symbol: {} for item in contexts}
        with ThreadPoolExecutor(max_workers=self.settings.enrichment_workers) as executor:
            futures = {
                executor.submit(self._call, dimension, item): (item.symbol, dimension)
                for item in contexts
                for dimension in self.providers
            }
            done, pending = wait(futures, timeout=self.settings.enrichment_timeout_seconds)
            for future in done:
                symbol, dimension = futures[future]
                values[symbol][dimension] = future.result()
            for future in pending:
                symbol, dimension = futures[future]
                future.cancel()
                values[symbol][dimension] = self._error_result(dimension)
        return {
            symbol: EnrichmentBundle(
                market=parts.get("market"),
                fundamental=parts.get("fundamental"),
                event_news=parts.get("event_news"),
                options=parts.get("options"),
            )
            for symbol, parts in values.items()
        }
