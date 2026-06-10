"""Dependency-injection container.

Wires settings -> database -> repositories -> providers -> services. The
provider singletons are resolved through the factory functions, so the concrete
class is chosen purely from configuration. Business components depend on the
abstract providers, never on the container's knowledge of which vendor won.
"""
from __future__ import annotations

from dependency_injector import containers, providers

from app.config import get_settings
from app.database.session import (
    create_db_engine,
    create_session_factory,
)
from app.factories import (
    active_adgroup_id,
    active_campaign_id,
    build_ad_platform,
    build_novelty_checker,
    build_qc_llm,
    build_script_generator,
    build_video_generator,
    build_video_spec,
    build_voice_generator,
)
from app.repositories import (
    AdGroupRepository,
    AdRepository,
    CampaignRepository,
    CreativeJobRepository,
    MetricRepository,
    ProductRepository,
    QcReviewRepository,
    ScriptRepository,
    VideoRepository,
)
from app.agents import (
    CreativeStrategistAgent,
    PerformanceAgent,
    QualityReviewAgent,
    TikTokAdAgent,
    VideoProductionAgent,
)
from app.orchestrator import CreativeJobOrchestrator
from app.services.adgroup_router import AdGroupRouter
from app.services.campaign_service import CampaignService
from app.services.creative_service import CreativeService
from app.services.knowledge_service import KnowledgeService
from app.services.monitoring_service import MonitoringService
from app.services.pause_rules import PauseRuleEngine
from app.services.profile_service import ProfileService
from app.services.qc_judge import QcJudge
from app.services.script_strategist import ScriptStrategist
from app.services.strategy import AngleSelector
from app.services.talking_head import TalkingHeadProducer
from app.services.video_merge import VideoMerger
from app.services.video_storage import VideoStorageService
from app.services.voiceover import VoiceoverService


class Container(containers.DeclarativeContainer):
    # ---- Configuration ----
    settings = providers.Singleton(get_settings)

    # ---- Database ----
    engine = providers.Singleton(create_db_engine, database_url=settings.provided.database_url)
    session_factory = providers.Singleton(create_session_factory, engine)

    # ---- Repositories ----
    product_repo = providers.Singleton(ProductRepository, session_factory)
    script_repo = providers.Singleton(ScriptRepository, session_factory)
    video_repo = providers.Singleton(VideoRepository, session_factory)
    ad_repo = providers.Singleton(AdRepository, session_factory)
    metric_repo = providers.Singleton(MetricRepository, session_factory)
    job_repo = providers.Singleton(CreativeJobRepository, session_factory)
    qc_repo = providers.Singleton(QcReviewRepository, session_factory)
    campaign_repo = providers.Singleton(CampaignRepository, session_factory)
    adgroup_repo = providers.Singleton(AdGroupRepository, session_factory)

    # ---- Providers (chosen from config via factories) ----
    script_generator = providers.Singleton(build_script_generator, settings)
    video_generator = providers.Singleton(build_video_generator, settings)
    voice_generator = providers.Singleton(build_voice_generator, settings)
    ad_platform = providers.Singleton(build_ad_platform, settings)
    video_merger = providers.Singleton(VideoMerger, ffmpeg=settings.provided.ffmpeg_path)
    voiceover_service = providers.Singleton(
        VoiceoverService,
        voice_generator=voice_generator,
        merger=video_merger,
        enabled=settings.provided.voice_enabled,
    )

    # ---- Infrastructure services ----
    storage = providers.Singleton(
        VideoStorageService, storage_dir=settings.provided.video_storage_dir
    )

    pause_rules = providers.Singleton(
        PauseRuleEngine,
        max_spend_no_conv=settings.provided.pause_max_spend_no_conv,
        min_ctr=settings.provided.pause_min_ctr,
        min_roas=settings.provided.pause_min_roas,
        min_spend_to_evaluate=settings.provided.pause_min_spend_to_evaluate,
    )

    # Brand / audience / creative-directive profiles (used by services + agents).
    profile_service = providers.Singleton(
        ProfileService, path=settings.provided.profiles_path
    )

    monitoring_service = providers.Singleton(
        MonitoringService,
        ad_platform=ad_platform,
        ad_repo=ad_repo,
        metric_repo=metric_repo,
        rule_engine=pause_rules,
    )

    # ---- Agent pipeline ----
    knowledge_service = providers.Singleton(
        KnowledgeService,
        script_repo=script_repo,
        qc_repo=qc_repo,
        metric_repo=metric_repo,
    )

    # The Creative Strategist uses the script provider as its LLM transport
    # (same vendor as SCRIPT_PROVIDER) and the Knowledge store for history.
    angle_selector = providers.Singleton(AngleSelector)
    novelty_checker = providers.Singleton(build_novelty_checker, settings)
    script_strategist = providers.Singleton(
        ScriptStrategist,
        llm=script_generator,
        knowledge=knowledge_service,
        profile_service=profile_service,
        selector=angle_selector,
        novelty=novelty_checker,
        creative_mode=settings.provided.creative_mode,
    )

    # One-shot pipeline. Uses the same Strategist as the agent path so
    # /products/generate and /jobs both honour profiles.json.
    creative_service = providers.Singleton(
        CreativeService,
        script_generator=script_generator,
        video_generator=video_generator,
        ad_platform=ad_platform,
        storage=storage,
        product_repo=product_repo,
        script_repo=script_repo,
        video_repo=video_repo,
        ad_repo=ad_repo,
        campaign_id=providers.Callable(active_campaign_id, settings),
        adgroup_id=providers.Callable(active_adgroup_id, settings),
        profile_service=profile_service,
        script_strategist=script_strategist,
        voiceover=voiceover_service,
    )

    strategist_agent = providers.Singleton(
        CreativeStrategistAgent,
        strategist=script_strategist,
        product_repo=product_repo,
        script_repo=script_repo,
    )
    talking_head_producer = providers.Singleton(
        TalkingHeadProducer,
        video_generator=video_generator,
        storage=storage,
        voice_generator=voice_generator,
    )
    video_agent = providers.Singleton(
        VideoProductionAgent,
        video_generator=video_generator,
        storage=storage,
        product_repo=product_repo,
        script_repo=script_repo,
        video_repo=video_repo,
        profile_service=profile_service,
        voiceover=voiceover_service,
        talking_head=talking_head_producer,
        creative_mode=settings.provided.creative_mode,
    )
    qc_llm = providers.Singleton(build_qc_llm, settings)
    qc_judge = providers.Singleton(
        QcJudge,
        llm=qc_llm,
        profile_service=profile_service,
        enabled=settings.provided.qc_llm_enabled,
    )
    video_spec = providers.Singleton(build_video_spec, settings)
    qc_agent = providers.Singleton(
        QualityReviewAgent,
        profile_service=profile_service,
        script_repo=script_repo,
        video_repo=video_repo,
        qc_repo=qc_repo,
        judge=qc_judge,
        video_spec=video_spec,
    )
    # Campaign cloning + ad-group routing.
    campaign_service = providers.Singleton(
        CampaignService,
        ad_platform=ad_platform,
        campaign_repo=campaign_repo,
        adgroup_repo=adgroup_repo,
        template_campaign_id=providers.Callable(active_campaign_id, settings),
    )
    adgroup_router = providers.Singleton(
        AdGroupRouter,
        campaign_repo=campaign_repo,
        adgroup_repo=adgroup_repo,
        default_adgroup_id=providers.Callable(active_adgroup_id, settings),
        default_campaign_id=providers.Callable(active_campaign_id, settings),
    )

    ad_agent = providers.Singleton(
        TikTokAdAgent,
        ad_platform=ad_platform,
        product_repo=product_repo,
        video_repo=video_repo,
        ad_repo=ad_repo,
        script_repo=script_repo,
        router=adgroup_router,
        campaign_id=providers.Callable(active_campaign_id, settings),
        adgroup_id=providers.Callable(active_adgroup_id, settings),
    )
    performance_agent = providers.Singleton(
        PerformanceAgent,
        ad_platform=ad_platform,
        ad_repo=ad_repo,
        metric_repo=metric_repo,
    )

    orchestrator = providers.Singleton(
        CreativeJobOrchestrator,
        job_repo=job_repo,
        strategist=strategist_agent,
        video_agent=video_agent,
        qc_agent=qc_agent,
        ad_agent=ad_agent,
    )
