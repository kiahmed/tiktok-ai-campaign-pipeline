"""Agent pipeline.

Five single-responsibility agents move a CreativeJob through the state machine:

  ① CreativeStrategistAgent  -> script candidate
  ② VideoProductionAgent     -> video candidate
  ③ QualityReviewAgent       -> APPROVE / REJECT (+reason saved to Knowledge)
  ④ TikTokAdAgent            -> create ad in the existing ad group
  ⑤ PerformanceAgent         -> measure metrics, feed Knowledge

Each implements the same :class:`Agent` contract. The Orchestrator dispatches
based on job status; agents never call each other directly.
"""
from app.agents.base import Agent, AgentResult
from app.agents.strategist import CreativeStrategistAgent
from app.agents.video_agent import VideoProductionAgent
from app.agents.qc_agent import QualityReviewAgent
from app.agents.ad_agent import TikTokAdAgent
from app.agents.performance_agent import PerformanceAgent

__all__ = [
    "Agent",
    "AgentResult",
    "CreativeStrategistAgent",
    "VideoProductionAgent",
    "QualityReviewAgent",
    "TikTokAdAgent",
    "PerformanceAgent",
]
