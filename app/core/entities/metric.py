from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class PerformanceMetrics:
    """A normalised performance snapshot for a single ad.

    Every ad platform exposes a different metrics schema; each AdPlatform
    provider maps its raw numbers into this common shape. Derived metrics
    (ctr, cpc, cpa, roas) are computed from the primitives when the platform
    does not supply them, so business rules can rely on them always existing.
    """

    spend: float = 0.0
    impressions: int = 0
    clicks: int = 0
    conversions: int = 0
    revenue: float = 0.0

    ctr: float = 0.0  # clicks / impressions
    cpc: float = 0.0  # spend / clicks
    cpa: float = 0.0  # spend / conversions
    roas: float = 0.0  # revenue / spend

    def with_derived(self) -> "PerformanceMetrics":
        """Return a copy with derived rates computed from the primitives."""
        ctr = (self.clicks / self.impressions) if self.impressions else 0.0
        cpc = (self.spend / self.clicks) if self.clicks else 0.0
        cpa = (self.spend / self.conversions) if self.conversions else 0.0
        roas = (self.revenue / self.spend) if self.spend else 0.0
        return PerformanceMetrics(
            spend=self.spend,
            impressions=self.impressions,
            clicks=self.clicks,
            conversions=self.conversions,
            revenue=self.revenue,
            ctr=ctr,
            cpc=cpc,
            cpa=cpa,
            roas=roas,
        )
