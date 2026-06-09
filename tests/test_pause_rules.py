"""Unit tests for the pause-rule engine (pure business logic)."""
from app.core.entities import PerformanceMetrics
from app.services.pause_rules import PauseRuleEngine


def engine() -> PauseRuleEngine:
    return PauseRuleEngine(
        max_spend_no_conv=50.0, min_ctr=0.005, min_roas=1.0, min_spend_to_evaluate=5.0
    )


def test_low_spend_is_never_paused():
    m = PerformanceMetrics(spend=2.0, impressions=1000, clicks=0).with_derived()
    assert engine().evaluate(m).should_pause is False


def test_rule1_spend_over_threshold_no_conversions():
    m = PerformanceMetrics(spend=60.0, impressions=10000, clicks=100, conversions=0).with_derived()
    decision = engine().evaluate(m)
    assert decision.should_pause is True
    assert "Rule 1" in decision.reason


def test_rule2_low_ctr():
    # 10000 impressions, 10 clicks -> CTR 0.1% < 0.5%
    m = PerformanceMetrics(spend=20.0, impressions=10000, clicks=10, conversions=1, revenue=30).with_derived()
    decision = engine().evaluate(m)
    assert decision.should_pause is True
    assert "Rule 2" in decision.reason


def test_rule3_low_roas():
    # Good CTR, has conversions, but ROAS 0.5 < 1.0
    m = PerformanceMetrics(spend=40.0, impressions=10000, clicks=500, conversions=2, revenue=20).with_derived()
    decision = engine().evaluate(m)
    assert decision.should_pause is True
    assert "Rule 3" in decision.reason


def test_healthy_ad_is_kept():
    m = PerformanceMetrics(spend=40.0, impressions=10000, clicks=500, conversions=10, revenue=120).with_derived()
    assert engine().evaluate(m).should_pause is False


def test_derived_metrics_are_computed():
    m = PerformanceMetrics(spend=10.0, impressions=1000, clicks=50, conversions=5, revenue=40).with_derived()
    assert round(m.ctr, 3) == 0.05
    assert round(m.cpc, 3) == 0.2
    assert round(m.cpa, 3) == 2.0
    assert round(m.roas, 3) == 4.0
