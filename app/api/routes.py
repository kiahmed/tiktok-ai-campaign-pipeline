"""HTTP routes. Dependencies are resolved from the DI container on app.state."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.dashboard_page import DASHBOARD_HTML
from app.api.schemas import (
    AdOut,
    CreativeResponse,
    AnglePerfOut,
    HealthResponse,
    JobOverviewItem,
    JobRequest,
    JobResponse,
    MetricOut,
    MonitoringRunResponse,
    OverviewItem,
    OverviewResponse,
    OverviewSummary,
    ProductRequest,
    QcReviewOut,
    ScriptGenRequest,
    ScriptGenResponse,
    StrategyInsight,
    VideoInfo,
)
from app.core.entities import ProductInput
from app.services.naming import slugify

logger = logging.getLogger("api")

router = APIRouter()


def _container(request: Request):
    return request.app.state.container


def _providers(request: Request) -> HealthResponse:
    s = _container(request).settings()
    return HealthResponse(
        status="ok",
        script_provider=s.script_provider,
        video_provider=s.video_provider,
        ad_platform=s.ad_platform,
    )


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health(request: Request) -> HealthResponse:
    return _providers(request)


@router.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/dashboard")


@router.get("/dashboard", response_class=HTMLResponse, tags=["dashboard"])
def dashboard() -> HTMLResponse:
    """Self-contained HTML monitoring dashboard."""
    return HTMLResponse(content=DASHBOARD_HTML)


@router.get("/api/overview", response_model=OverviewResponse, tags=["dashboard"])
def overview(request: Request) -> OverviewResponse:
    """Aggregated view powering the dashboard: every ad with its video and
    latest metrics, plus rollup summary numbers."""
    c = _container(request)
    ads = c.ad_repo().list_all()

    video_ids = [a.video_id for a in ads if a.video_id]
    videos = c.video_repo().get_many(video_ids)
    latest = c.metric_repo().latest_for_ads([a.id for a in ads])

    items: list[OverviewItem] = []
    total_spend = 0.0
    total_conv = 0
    roas_values: list[float] = []
    active = paused = failed = 0

    for a in ads:
        status = a.status.value
        if status == "ACTIVE":
            active += 1
        elif status == "PAUSED":
            paused += 1
        elif status == "FAILED":
            failed += 1

        vinfo = None
        v = videos.get(a.video_id)
        if v is not None:
            vinfo = VideoInfo(
                file_name=v.file_name,
                url=f"/videos/{v.file_name}",
                aspect_ratio=v.aspect_ratio,
                duration_seconds=v.duration_seconds,
                provider=v.provider,
            )

        metrics_out = None
        measured_at = None
        m = latest.get(a.id)
        if m is not None:
            metrics_out = MetricOut(
                captured_at=m.captured_at.isoformat(),
                spend=m.spend,
                impressions=m.impressions,
                clicks=m.clicks,
                conversions=m.conversions,
                revenue=m.revenue,
                ctr=m.ctr,
                cpc=m.cpc,
                cpa=m.cpa,
                roas=m.roas,
            )
            measured_at = m.captured_at.isoformat()
            total_spend += m.spend
            total_conv += m.conversions
            if m.spend > 0:
                roas_values.append(m.roas)

        items.append(
            OverviewItem(
                id=a.id,
                name=a.name,
                platform=a.platform,
                status=status,
                ad_id=a.ad_id,
                creative_id=a.creative_id,
                platform_video_id=a.platform_video_id,
                pause_reason=a.pause_reason,
                created_at=a.created_at.isoformat(),
                video=vinfo,
                latest_metrics=metrics_out,
                measured_at=measured_at,
            )
        )

    summary = OverviewSummary(
        total_ads=len(ads),
        active=active,
        paused=paused,
        failed=failed,
        total_spend=round(total_spend, 2),
        total_conversions=total_conv,
        avg_roas=round(sum(roas_values) / len(roas_values), 2) if roas_values else 0.0,
    )
    return OverviewResponse(summary=summary, providers=_providers(request), ads=items)


@router.post("/scripts/generate", response_model=ScriptGenResponse, tags=["creatives"])
def generate_script(request: Request, body: ScriptGenRequest) -> ScriptGenResponse:
    """Generate ONLY a script (profiles-aware Strategist) — no video, no ad,
    and nothing is persisted. Use it to iterate on profiles.json / prompts
    cheaply before committing to video generation."""
    c = _container(request)
    # Treat 0 / null as "no product_id" (IDs start at 1; Swagger auto-fills 0).
    if body.product_id:
        product = c.product_repo().get(body.product_id)
        if product is None:
            raise HTTPException(status_code=404, detail=f"product {body.product_id} not found")
        product_input = ProductInput(
            name=product.name,
            image_url=product.image_url,
            description=product.description,
            benefits=[b for b in (product.benefits or "").split("\n") if b.strip()],
        )
        product_id = product.id
    else:
        if not body.name:
            raise HTTPException(status_code=422, detail="provide product_id or name")
        product_input = ProductInput(
            name=body.name, image_url="", description=body.description, benefits=body.benefits
        )
        product_id = 0  # no history context

    out = c.script_strategist().generate(product_input, product_id)
    return ScriptGenResponse(
        hook_type=out.hook_type,
        angle=out.angle,
        audience_segment=out.audience_segment,
        script=out.script,
        word_count=len(out.script.split()),
        mode=out.mode,
        similarity=round(out.similarity, 3),
        provider=out.provider,
    )


@router.post("/products/generate", response_model=CreativeResponse, tags=["creatives"])
def generate_creative(request: Request, body: ProductRequest) -> CreativeResponse:
    """Run the full pipeline: script -> video -> download -> upload -> ad.

    Domain errors (ConfigurationError / ProviderError / ...) propagate to the
    centralised exception handlers in ``app.main``, which map them to clean JSON
    responses (400 / 502 / 500). No vendor traceback ever reaches the client.
    """
    service = _container(request).creative_service()
    product = ProductInput(
        name=body.name,
        image_url=str(body.image_url),
        description=body.description,
        benefits=body.benefits,
    )
    result = service.run(
        product,
        script_text=body.script,
        deploy=body.deploy,
        landing_page_url=body.landing_page_url,
    )
    return CreativeResponse(
        product_id=result.product_id,
        script_id=result.script_id,
        video_id=result.video_id,
        script_text=result.script_text,
        script_provider=result.script_provider,
        local_video_path=result.local_video_path,
        deployed=result.deployed,
        ad_row_id=result.ad_row_id,
        platform_video_id=result.platform_video_id,
        creative_id=result.creative_id,
        ad_id=result.ad_id,
    )


@router.post("/monitoring/run", response_model=MonitoringRunResponse, tags=["monitoring"])
def run_monitoring(request: Request) -> MonitoringRunResponse:
    """Trigger a monitoring pass immediately (same logic the scheduler runs)."""
    summary = _container(request).monitoring_service().run_once()
    return MonitoringRunResponse(
        evaluated=summary.evaluated,
        paused=summary.paused,
        errors=summary.errors,
        paused_ad_ids=summary.paused_ad_ids,
    )


@router.get("/ads", response_model=list[AdOut], tags=["ads"])
def list_ads(request: Request) -> list[AdOut]:
    ads = _container(request).ad_repo().list_all()
    return [
        AdOut(
            id=a.id,
            name=a.name,
            platform=a.platform,
            status=a.status.value,
            ad_id=a.ad_id,
            creative_id=a.creative_id,
            platform_video_id=a.platform_video_id,
            pause_reason=a.pause_reason,
        )
        for a in ads
    ]


@router.get("/ads/{ad_pk}/metrics", response_model=list[MetricOut], tags=["ads"])
def ad_metrics(request: Request, ad_pk: int) -> list[MetricOut]:
    container = _container(request)
    if container.ad_repo().get(ad_pk) is None:
        raise HTTPException(status_code=404, detail=f"ad {ad_pk} not found")
    rows = container.metric_repo().history(ad_pk)
    return [
        MetricOut(
            captured_at=r.captured_at.isoformat(),
            spend=r.spend,
            impressions=r.impressions,
            clicks=r.clicks,
            conversions=r.conversions,
            revenue=r.revenue,
            ctr=r.ctr,
            cpc=r.cpc,
            cpa=r.cpa,
            roas=r.roas,
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Agent pipeline / jobs
# ---------------------------------------------------------------------------
def _serialize_job(container, job) -> JobResponse:
    reviews = container.qc_repo().list_for_job(job.id)
    return JobResponse(
        id=job.id,
        product_id=job.product_id,
        status=job.status.value,
        attempt=job.attempt,
        max_attempts=job.max_attempts,
        script_id=job.script_id,
        video_id=job.video_id,
        ad_id=job.ad_id,
        last_error=job.last_error,
        discard_reason=job.discard_reason,
        qc_reviews=[
            QcReviewOut(
                verdict=r.verdict.value,
                score=r.score,
                reasons=[x for x in r.reasons.split("\n") if x],
                failure_codes=[x for x in r.failure_codes.split(",") if x],
                reviewer=r.reviewer,
                attempt=r.attempt,
                created_at=r.created_at.isoformat(),
            )
            for r in reviews
        ],
    )


@router.post("/jobs", response_model=JobResponse, tags=["jobs"])
def create_job(request: Request, body: JobRequest) -> JobResponse:
    """Create a creative job and run it through the agent pipeline.

    Strategist -> Video -> Quality Review -> (Ad). Runs synchronously and
    returns the final job state (incl. QC reviews). Domain errors are mapped to
    JSON by the centralised handlers.
    """
    c = _container(request)
    # Treat 0 / null as "no product_id" (IDs start at 1; Swagger auto-fills 0).
    if body.product_id:
        product = c.product_repo().get(body.product_id)
        if product is None:
            raise HTTPException(status_code=404, detail=f"product {body.product_id} not found")
    else:
        if not body.name or not body.image_url:
            raise HTTPException(
                status_code=422,
                detail="provide product_id, or both name and image_url for a new product",
            )
        product = c.product_repo().create(
            name=body.name,
            slug=slugify(body.name),
            image_url=str(body.image_url),
            description=body.description,
            benefits=body.benefits,
        )
    job = c.job_repo().create(
        product_id=product.id,
        prepared_script=body.prepared_script,
        landing_page_url=body.landing_page_url,
        post_to_platform=body.post_to_platform,
        max_attempts=c.settings().job_max_attempts,
    )
    final = c.orchestrator().process(job.id)
    return _serialize_job(c, final)


@router.get("/jobs", response_model=list[JobResponse], tags=["jobs"])
def list_jobs(request: Request) -> list[JobResponse]:
    c = _container(request)
    return [_serialize_job(c, j) for j in c.job_repo().list_all()]


@router.get("/jobs/{job_id}", response_model=JobResponse, tags=["jobs"])
def get_job(request: Request, job_id: int) -> JobResponse:
    c = _container(request)
    job = c.job_repo().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job {job_id} not found")
    return _serialize_job(c, job)


@router.post("/jobs/{job_id}/measure", response_model=JobResponse, tags=["jobs"])
def measure_job(request: Request, job_id: int) -> JobResponse:
    """Run the Performance agent once for a LIVE job (stores a metrics snapshot)."""
    c = _container(request)
    job = c.job_repo().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job {job_id} not found")
    c.performance_agent().run(job)
    return _serialize_job(c, job)


@router.get("/api/jobs/overview", response_model=list[JobOverviewItem], tags=["dashboard"])
def jobs_overview(request: Request) -> list[JobOverviewItem]:
    """Jobs with their script strategy, video, and latest QC verdict (dashboard)."""
    c = _container(request)
    jobs = c.job_repo().list_all()
    names = {p.id: p.name for p in c.product_repo().list_all()}
    items: list[JobOverviewItem] = []
    for j in jobs:
        script = c.script_repo().get(j.script_id) if j.script_id else None
        video = c.video_repo().get(j.video_id) if j.video_id else None
        reviews = c.qc_repo().list_for_job(j.id)
        last = reviews[-1] if reviews else None
        ad_external = None
        if j.ad_id:
            ad_row = c.ad_repo().get(j.ad_id)
            ad_external = ad_row.ad_id if ad_row else None
        items.append(
            JobOverviewItem(
                id=j.id,
                product_id=j.product_id,
                product_name=names.get(j.product_id, "?"),
                status=j.status.value,
                attempt=j.attempt,
                max_attempts=j.max_attempts,
                angle=script.angle if script else None,
                hook_type=script.hook_type if script else None,
                audience_segment=script.audience_segment if script else None,
                script_text=script.text if script else None,
                video_url=f"/videos/{video.file_name}" if video else None,
                ad_id=ad_external,
                last_qc_verdict=last.verdict.value if last else None,
                last_qc_codes=[x for x in last.failure_codes.split(",") if x] if last else [],
                last_qc_reasons=[x for x in last.reasons.split("\n") if x] if last else [],
                discard_reason=j.discard_reason,
                created_at=j.created_at.isoformat(),
            )
        )
    return items


@router.get("/api/strategy/insights", response_model=list[StrategyInsight], tags=["dashboard"])
def strategy_insights(request: Request) -> list[StrategyInsight]:
    """Per-product 'Strategy Brain': angle/hook performance ranking + what the
    Strategist will avoid (overused + recent rejection codes)."""
    c = _container(request)
    knowledge = c.knowledge_service()
    out: list[StrategyInsight] = []
    for product in c.product_repo().list_all():
        ctx = knowledge.context_for(product.id)
        if not ctx.past_scripts:
            continue
        out.append(
            StrategyInsight(
                product_id=product.id,
                product_name=product.name,
                angle_performance=_perf_list(ctx.angle_perf),
                hook_performance=_perf_list(ctx.hook_perf),
                overused_angles=ctx.overused_angles,
                overused_hooks=ctx.overused_hooks,
                recent_failure_codes=ctx.recent_failure_codes,
                scripts_count=len(ctx.past_scripts),
            )
        )
    return out


def _perf_list(perf: dict) -> list[AnglePerfOut]:
    rows = [
        AnglePerfOut(
            key=k,
            count=v.count,
            avg_ctr=round(v.avg_ctr, 5),
            avg_roas=round(v.avg_roas, 3),
            score=round(v.score, 5),
        )
        for k, v in perf.items()
    ]
    rows.sort(key=lambda r: r.score, reverse=True)
    return rows
