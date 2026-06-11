"""Self-contained HTML for the monitoring dashboard.

Served at ``GET /dashboard``. A single static page (no build step) with three
tabs that talk to the JSON API with vanilla ``fetch``:
  * Ads            — live ad performance (/api/overview)
  * Jobs           — agent pipeline state + QC verdicts (/api/jobs/overview)
  * Strategy Brain — angle/hook performance the Strategist exploits
                     (/api/strategy/insights)
Chart.js (CDN) powers the per-ad history chart; tables work without it.
"""
from __future__ import annotations

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Ad Automation Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root { --bg:#0f1218; --card:#171c26; --line:#262d3a; --txt:#e6e9ef; --muted:#9aa4b2;
          --green:#2ecc71; --red:#e74c3c; --amber:#f1c40f; --blue:#4aa3ff; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--txt);
         font:14px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; }
  header { display:flex; align-items:center; gap:16px; padding:16px 24px;
           border-bottom:1px solid var(--line); position:sticky; top:0; background:var(--bg); z-index:5; }
  header h1 { font-size:18px; margin:0; }
  .providers { color:var(--muted); font-size:12px; }
  .spacer { flex:1; }
  button { background:var(--blue); color:#04111f; border:0; border-radius:8px;
           padding:8px 14px; font-weight:600; cursor:pointer; }
  button.secondary { background:var(--card); color:var(--txt); border:1px solid var(--line); }
  button:disabled { opacity:.5; cursor:default; }
  nav { display:flex; gap:8px; padding:12px 24px 0; }
  .tab { background:var(--card); border:1px solid var(--line); border-bottom:0;
         padding:8px 16px; border-radius:8px 8px 0 0; cursor:pointer; color:var(--muted); }
  .tab.active { color:var(--txt); background:#1c2330; font-weight:600; }
  main { padding:16px 24px 32px; max-width:1280px; margin:0 auto; }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-bottom:20px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px 16px; }
  .card .k { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.04em; }
  .card .v { font-size:24px; font-weight:700; margin-top:4px; }
  table { width:100%; border-collapse:collapse; background:var(--card);
          border:1px solid var(--line); border-radius:12px; overflow:hidden; margin-bottom:20px; }
  th,td { padding:10px 12px; text-align:right; border-bottom:1px solid var(--line); white-space:nowrap; }
  th:first-child,td:first-child { text-align:left; }
  th { color:var(--muted); font-weight:600; font-size:12px; text-transform:uppercase; }
  tr:last-child td { border-bottom:0; }
  tr.adrow:hover { background:#1c2330; }
  .badge { padding:2px 9px; border-radius:999px; font-size:12px; font-weight:600; }
  .ACTIVE,.LIVE,.APPROVE { background:rgba(46,204,113,.15); color:var(--green); }
  .PAUSED,.APPROVED,.SCRIPTED,.VIDEO_READY,.DRAFT { background:rgba(241,196,15,.15); color:var(--amber); }
  .FAILED,.REJECTED,.DISCARDED,.REJECT { background:rgba(231,76,60,.15); color:var(--red); }
  .muted { color:var(--muted); }
  .linklike { color:var(--blue); cursor:pointer; text-decoration:underline; }
  .detail { background:#10141c; }
  .detail td { padding:16px; }
  .detailgrid { display:grid; grid-template-columns:280px 1fr; gap:24px; }
  video { width:260px; border-radius:10px; border:1px solid var(--line); background:#000; }
  .reason { color:var(--amber); font-size:12px; white-space:normal; }
  .chip { display:inline-block; background:#1c2330; border:1px solid var(--line); border-radius:999px;
          padding:1px 8px; font-size:11px; margin:2px 4px 2px 0; }
  .chip.bad { color:var(--red); border-color:rgba(231,76,60,.4); }
  .empty { text-align:center; color:var(--muted); padding:48px; }
  .sbcard { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px; margin-bottom:16px; }
  .sbcard h3 { margin:0 0 4px; font-size:15px; }
  .hide { display:none; }
  #toast { position:fixed; bottom:20px; right:20px; background:var(--card);
           border:1px solid var(--line); padding:12px 16px; border-radius:10px; display:none; }
  .modal { position:fixed; inset:0; background:rgba(0,0,0,.6); display:none; z-index:20;
           align-items:flex-start; justify-content:center; padding:40px 16px; overflow:auto; }
  .modal.show { display:flex; }
  .modalbox { background:var(--card); border:1px solid var(--line); border-radius:12px;
              width:100%; max-width:880px; padding:20px 24px; }
  .modalbox h3 { margin:0 0 12px; font-size:16px; }
  .callcard { border:1px solid var(--line); border-radius:10px; padding:12px 14px; margin-bottom:12px; background:#10141c; }
  .callcard .hd { display:flex; gap:10px; align-items:center; margin-bottom:8px; }
  .callcard .meth { font-weight:700; color:var(--blue); }
  .callcard pre { background:#0b0e14; border:1px solid var(--line); border-radius:8px; margin:6px 0 0;
                  padding:10px; overflow:auto; max-height:260px; font-size:12px; white-space:pre-wrap; word-break:break-word; }
  .closeX { float:right; cursor:pointer; color:var(--muted); font-size:20px; line-height:1; }
</style>
</head>
<body>
<header>
  <h1>📊 Ad Automation</h1>
  <span class="providers" id="providers"></span>
  <span class="spacer"></span>
  <span class="providers" id="updated"></span>
  <button class="secondary" onclick="load()">Refresh</button>
  <button id="monBtn" onclick="runMonitoring()">Run monitoring now</button>
</header>
<nav>
  <div class="tab active" data-tab="ads" onclick="showTab('ads')">Ads</div>
  <div class="tab" data-tab="jobs" onclick="showTab('jobs')">Jobs</div>
  <div class="tab" data-tab="preview" onclick="showTab('preview')">Preview</div>
  <div class="tab" data-tab="logs" onclick="showTab('logs')">Logs</div>
  <div class="tab" data-tab="strategy" onclick="showTab('strategy')">Strategy Brain</div>
</nav>
<main>
  <section id="tab-ads">
    <div class="cards" id="cards"></div>
    <div id="adsWrap"></div>
  </section>
  <section id="tab-jobs" class="hide"><div id="jobsWrap"></div></section>
  <section id="tab-preview" class="hide">
    <div class="sbcard">
      <h3>Dry-run preview</h3>
      <div class="muted" style="margin-bottom:12px">Generate the script and assemble the exact video API payload (avatar/voice, background scene prompt, full request) — WITHOUT generating media or spending HeyGen/Imagen credits.</div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">
        <input id="pvProductId" placeholder="product_id (optional)" style="width:160px;padding:8px;background:#0b0e14;border:1px solid var(--line);border-radius:8px;color:var(--txt)">
        <input id="pvName" placeholder="or product name" style="width:220px;padding:8px;background:#0b0e14;border:1px solid var(--line);border-radius:8px;color:var(--txt)">
        <input id="pvImage" placeholder="image_url (optional)" style="width:240px;padding:8px;background:#0b0e14;border:1px solid var(--line);border-radius:8px;color:var(--txt)">
        <button id="pvBtn" onclick="runPreview()">Run preview</button>
      </div>
      <textarea id="pvScript" placeholder="optional: paste a script to preview verbatim (skips generation)" style="margin-top:10px;width:100%;min-height:64px;padding:8px;background:#0b0e14;border:1px solid var(--line);border-radius:8px;color:var(--txt)"></textarea>
    </div>
    <div id="previewWrap"></div>
    <div class="sbcard" style="margin-top:16px">
      <h3>Preview history</h3>
      <div class="muted" style="margin-bottom:8px">Past dry runs. Click any to view its stored script, scene prompt and payload.</div>
      <div id="previewHistory"></div>
    </div>
  </section>
  <section id="tab-logs" class="hide">
    <div class="sbcard" style="display:flex;align-items:center;gap:12px">
      <div><h3 style="margin:0">API call log</h3>
        <div class="muted">Every provider API call across all videos (jobs AND /products/generate), newest first — script, avatar/voice selection, generated background image, payload & status.</div></div>
      <span class="spacer" style="flex:1"></span>
      <button class="secondary" onclick="loadLogs()">Refresh</button>
    </div>
    <div id="logsWrap"></div>
  </section>
  <section id="tab-strategy" class="hide"><div id="strategyWrap"></div></section>
</main>
<div id="toast"></div>
<div id="callsModal" class="modal" onclick="if(event.target===this)closeCalls()">
  <div class="modalbox">
    <span class="closeX" onclick="closeCalls()">×</span>
    <h3 id="callsTitle">API call history</h3>
    <div id="callsBody"></div>
  </div>
</div>

<script>
const fmtMoney = v => '$' + (Number(v)||0).toFixed(2);
const fmtPct   = v => ((Number(v)||0)*100).toFixed(2) + '%';
const fmtNum   = v => (Number(v)||0).toLocaleString();
const esc = s => (s==null?'':String(s)).replace(/[&<>]/g, m=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[m]));
const charts = {};
let current = 'ads';

function toast(msg){ const t=document.getElementById('toast'); t.textContent=msg; t.style.display='block'; setTimeout(()=>t.style.display='none',3500); }
function showTab(name){
  current = name;
  document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active', t.dataset.tab===name));
  ['ads','jobs','preview','logs','strategy'].forEach(n=>document.getElementById('tab-'+n).classList.toggle('hide', n!==name));
  if(name==='preview') loadPreviews();
  if(name==='logs') loadLogs();
}

async function load(){
  try {
    const [ov, jobs, ins] = await Promise.all([
      fetch('/api/overview').then(r=>r.json()),
      fetch('/api/jobs/overview').then(r=>r.json()),
      fetch('/api/strategy/insights').then(r=>r.json()),
    ]);
    renderAds(ov); renderJobs(jobs); renderStrategy(ins);
    document.getElementById('updated').textContent = 'updated ' + new Date().toLocaleTimeString();
  } catch(e){ toast('Failed to load: ' + e.message); }
}

/* ---------- Ads tab ---------- */
function renderAds(data){
  const p = data.providers;
  document.getElementById('providers').textContent =
    `script: ${p.script_provider} · video: ${p.video_provider} · ads: ${p.ad_platform}`;
  const s = data.summary;
  document.getElementById('cards').innerHTML = [
    ['Total ads', s.total_ads],['Active', s.active],['Paused', s.paused],['Failed', s.failed],
    ['Total spend', fmtMoney(s.total_spend)],['Conversions', fmtNum(s.total_conversions)],
    ['Avg ROAS', (Number(s.avg_roas)||0).toFixed(2)],
  ].map(([k,v])=>`<div class="card"><div class="k">${k}</div><div class="v">${v}</div></div>`).join('');

  if(!data.ads.length){ document.getElementById('adsWrap').innerHTML='<div class="empty">No ads yet.</div>'; return; }
  const head = `<tr><th>Ad</th><th>Status</th><th>Spend</th><th>Impr.</th><th>Clicks</th>
    <th>CTR</th><th>CPC</th><th>Conv.</th><th>CPA</th><th>ROAS</th><th>Video</th></tr>`;
  const rows = data.ads.map(ad=>{
    const m=ad.latest_metrics;
    const cell = m ? `<td>${fmtMoney(m.spend)}</td><td>${fmtNum(m.impressions)}</td><td>${fmtNum(m.clicks)}</td>
      <td>${fmtPct(m.ctr)}</td><td>${fmtMoney(m.cpc)}</td><td>${fmtNum(m.conversions)}</td>
      <td>${fmtMoney(m.cpa)}</td><td>${(Number(m.roas)||0).toFixed(2)}</td>` : `<td colspan="8" class="muted">no metrics yet</td>`;
    const vid = ad.video&&ad.video.url ? `<a class="linklike" href="${ad.video.url}" target="_blank">view</a>`:'<span class="muted">—</span>';
    const reason = ad.pause_reason ? `<div class="reason">⏸ ${esc(ad.pause_reason)}</div>`:'';
    return `<tr class="adrow" onclick="toggle(${ad.id})"><td>${esc(ad.name)}${reason}</td>
      <td><span class="badge ${ad.status}">${ad.status}</span></td>${cell}<td>${vid}</td></tr>
      <tr class="detail" id="detail-${ad.id}" style="display:none"><td colspan="11">${detailHtml(ad)}</td></tr>`;
  }).join('');
  document.getElementById('adsWrap').innerHTML = `<table>${head}${rows}</table>`;
}
function detailHtml(ad){
  const v=ad.video;
  const preview = v&&v.url ? `<video src="${v.url}" controls preload="metadata"></video>
     <div class="muted" style="margin-top:8px">${esc(v.file_name)}<br>${v.provider} · ${v.aspect_ratio}</div>`:'<div class="muted">No local video.</div>';
  return `<div class="detailgrid"><div>${preview}</div>
     <div><canvas id="chart-${ad.id}" height="120"></canvas><div id="hist-${ad.id}" class="muted" style="margin-top:8px">Loading…</div></div></div>`;
}
async function toggle(id){
  const row=document.getElementById('detail-'+id); const open=row.style.display!=='none';
  row.style.display=open?'none':'table-row'; if(open) return;
  try{ const h=await fetch('/ads/'+id+'/metrics').then(r=>r.json()); drawHistory(id,h);}catch(e){document.getElementById('hist-'+id).textContent='Failed.';}
}
function drawHistory(id,hist){
  const note=document.getElementById('hist-'+id);
  if(!hist.length){ note.textContent='No history yet.'; return; }
  note.textContent=hist.length+' snapshot(s)';
  if(typeof Chart==='undefined') return;
  if(charts[id]) charts[id].destroy();
  charts[id]=new Chart(document.getElementById('chart-'+id),{type:'line',
    data:{labels:hist.map(h=>new Date(h.captured_at).toLocaleString()),datasets:[
      {label:'Spend',data:hist.map(h=>h.spend),borderColor:'#4aa3ff',tension:.3,yAxisID:'y'},
      {label:'ROAS',data:hist.map(h=>h.roas),borderColor:'#2ecc71',tension:.3,yAxisID:'y2'},
      {label:'CTR %',data:hist.map(h=>h.ctr*100),borderColor:'#f1c40f',tension:.3,yAxisID:'y2'}]},
    options:{plugins:{legend:{labels:{color:'#9aa4b2'}}},scales:{x:{ticks:{color:'#9aa4b2'}},
      y:{position:'left',ticks:{color:'#9aa4b2'}},y2:{position:'right',ticks:{color:'#9aa4b2'},grid:{drawOnChartArea:false}}}}});
}

/* ---------- Jobs tab ---------- */
let JOBS_BY_ID = {};
function renderJobs(jobs){
  JOBS_BY_ID = {}; jobs.forEach(j=>{ JOBS_BY_ID[j.id]=j; });
  if(!jobs.length){ document.getElementById('jobsWrap').innerHTML='<div class="empty">No jobs yet. POST /jobs to start one.</div>'; return; }
  const head = `<tr><th>#</th><th>Product</th><th>Status</th><th>Angle</th><th>Hook</th>
    <th>Script</th><th>QC</th><th>Attempt</th><th>Video</th><th>Notes</th></tr>`;
  const rows = jobs.map(j=>{
    const qc = j.last_qc_verdict ? `<span class="badge ${j.last_qc_verdict}">${j.last_qc_verdict}</span>` : '<span class="muted">—</span>';
    const codes = (j.last_qc_codes||[]).map(c=>`<span class="chip bad">${esc(c)}</span>`).join('');
    const viewLink = j.video_url ? `<a class="linklike" href="${j.video_url}" target="_blank">view</a>` : '';
    const callsLink = j.video_id ? `<a class="linklike" onclick="showCalls(${j.video_id})">calls</a>` : '';
    const vid = (viewLink || callsLink)
      ? [viewLink, callsLink].filter(Boolean).join(' · ')
      : '<span class="muted">—</span>';
    const note = j.discard_reason ? `<span class="reason">${esc(j.discard_reason)}</span>` : codes || '<span class="muted">—</span>';
    const script = j.script_text
      ? `<div style="text-align:left;max-width:340px;white-space:normal;font-size:12px;line-height:1.4">${esc(j.script_text)}
         <div style="margin-top:6px"><a class="linklike" onclick="showScript(${j.id})">{ } script json</a></div></div>`
      : '<span class="muted">—</span>';
    return `<tr><td>${j.id}</td><td>${esc(j.product_name)}</td>
      <td><span class="badge ${j.status}">${j.status}</span></td>
      <td>${esc(j.angle)||'<span class="muted">—</span>'}</td>
      <td>${esc(j.hook_type)||'<span class="muted">—</span>'}</td>
      <td>${script}</td>
      <td>${qc}</td><td>${j.attempt}/${j.max_attempts}</td><td>${vid}</td>
      <td style="text-align:left">${note}</td></tr>`;
  }).join('');
  document.getElementById('jobsWrap').innerHTML = `<table>${head}${rows}</table>`;
}

/* ---------- Dry-run preview ---------- */
async function runPreview(){
  const btn = document.getElementById('pvBtn'); btn.disabled = true; btn.textContent='Running…';
  const wrap = document.getElementById('previewWrap');
  wrap.innerHTML = '<div class="muted">Generating script + assembling payload…</div>';
  const pid = document.getElementById('pvProductId').value.trim();
  const body = {
    product_id: pid ? Number(pid) : null,
    name: document.getElementById('pvName').value.trim() || null,
    image_url: document.getElementById('pvImage').value.trim() || null,
    prepared_script: document.getElementById('pvScript').value.trim() || null
  };
  try {
    const r = await fetch('/api/preview', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const d = await r.json();
    if(!r.ok){ wrap.innerHTML = `<div class="empty">${esc(d.detail||'Preview failed')}</div>`; return; }
    wrap.innerHTML = renderPreviewResult(d);
    loadPreviews();   // refresh history with the new run
  } catch(e){ wrap.innerHTML = '<div class="empty">Preview request failed.</div>'; }
  finally { btn.disabled=false; btn.textContent='Run preview'; }
}

function renderPreviewResult(d){
  const block = (label,obj)=>`<div class="callcard"><div class="hd"><span class="meth">${label}</span>${d.id?`<span class="muted" style="margin-left:auto">preview #${d.id}</span>`:''}</div>
    <pre>${esc(JSON.stringify(obj,null,2))}</pre></div>`;
  const scene = d.scene_prompt ? `<div class="callcard" style="border-color:rgba(46,204,113,.4)"><div class="hd"><span class="meth" style="color:var(--green)">BACKGROUND SCENE PROMPT</span></div><pre>${esc(d.scene_prompt)}</pre></div>` : '';
  const calls = (d.calls||[]).map(c=>{
    const req = c.request!=null ? `<div class="muted">request</div><pre>${esc(JSON.stringify(c.request,null,2))}</pre>`:'';
    const res = c.response!=null ? `<div class="muted">response</div><pre>${esc(JSON.stringify(c.response,null,2))}</pre>`:'';
    return `<div class="callcard"><div class="hd"><span class="meth">${esc(c.method)}</span><span>${esc(c.endpoint)}</span></div>${req}${res}</div>`;
  }).join('');
  return block('SCRIPT', d.script) + scene + block('API PAYLOAD (what would be sent)', d.payload)
    + `<div class="sbcard"><h3>Dry-run steps</h3>${calls}</div>`;
}

async function loadPreviews(){
  const el = document.getElementById('previewHistory');
  try {
    const runs = await fetch('/api/previews').then(r=>r.json());
    if(!runs.length){ el.innerHTML='<div class="muted">No previews yet.</div>'; return; }
    const head = `<tr><th>#</th><th>Product</th><th>Provider</th><th>When</th><th></th></tr>`;
    const rows = runs.map(p=>`<tr><td>${p.id}</td><td>${esc(p.product_name)||'<span class="muted">—</span>'}</td>
      <td>${esc(p.provider)}</td><td class="muted">${esc(new Date(p.created_at).toLocaleString())}</td>
      <td><a class="linklike" onclick="showPreviewDetail(${p.id})">view</a></td></tr>`).join('');
    el.innerHTML = `<table>${head}${rows}</table>`;
  } catch(e){ el.innerHTML='<div class="muted">Failed to load history.</div>'; }
}

async function showPreviewDetail(id){
  const wrap = document.getElementById('previewWrap');
  wrap.innerHTML = '<div class="muted">Loading preview…</div>';
  window.scrollTo({top:0,behavior:'smooth'});
  try {
    const d = await fetch('/api/previews/'+id).then(r=>r.json());
    wrap.innerHTML = renderPreviewResult(d);
  } catch(e){ wrap.innerHTML = '<div class="empty">Failed to load preview.</div>'; }
}

/* ---------- Global API call log ---------- */
function collectImages(obj){
  const urls=[];
  const walk=v=>{
    if(v==null) return;
    if(typeof v==='string'){
      if(/^https?:\/\/\S+\.(png|jpe?g|webp|gif)(\?|#|$)/i.test(v) || /heygen\.(ai|com)\/image/i.test(v)
         || /^\/videos\/\S+\.(png|jpe?g|webp|gif)$/i.test(v)) urls.push(v);  // local b-roll scenes
      return;
    }
    if(Array.isArray(v)){ v.forEach(walk); return; }
    if(typeof v==='object'){ Object.values(v).forEach(walk); }
  };
  walk(obj);
  return [...new Set(urls)];
}
async function loadLogs(){
  const wrap=document.getElementById('logsWrap');
  wrap.innerHTML='<div class="muted">Loading…</div>';
  try{
    const calls=await fetch('/api/calls').then(r=>r.json());
    if(!calls.length){ wrap.innerHTML='<div class="empty">No API calls logged yet. Generate a video to populate the log.</div>'; return; }
    wrap.innerHTML = calls.map(c=>{
      const imgs=[...collectImages(c.request_payload), ...collectImages(c.response_body)];
      const thumbs = imgs.length ? `<div style="display:flex;gap:8px;flex-wrap:wrap;margin:8px 0">`+
        imgs.map(u=>`<a href="${u}" target="_blank" title="${esc(u)}"><img src="${u}" loading="lazy" style="height:96px;border-radius:8px;border:1px solid var(--line);background:#000"></a>`).join('')+`</div>` : '';
      const code=c.status_code!=null?` · <span class="muted">HTTP ${c.status_code}</span>`:'';
      const req=c.request_payload!=null?`<div class="muted">request</div><pre>${esc(JSON.stringify(c.request_payload,null,2))}</pre>`:'';
      const res=c.response_body!=null?`<div class="muted">response</div><pre>${esc(JSON.stringify(c.response_body,null,2))}</pre>`:'';
      const isImg=String(c.method).startsWith('IMAGE');
      const meth = isImg?' style="color:var(--green)"':'';
      return `<div class="callcard"${isImg?' style="border-color:rgba(46,204,113,.4)"':''}>
        <div class="hd"><span class="meth"${meth}>${esc(c.method)}</span><span>${esc(c.endpoint)}</span>${code}
        <span class="muted" style="margin-left:auto">video #${c.video_id} · ${esc(c.provider)} · ${esc(new Date(c.created_at).toLocaleString())}</span></div>
        ${thumbs}${req}${res}</div>`;
    }).join('');
  }catch(e){ wrap.innerHTML='<div class="empty">Failed to load logs.</div>'; }
}

/* ---------- Script JSON per video/job ---------- */
function showScript(jobId){
  const j = JOBS_BY_ID[jobId]; if(!j) return;
  const obj = {
    hook_type: j.hook_type, angle: j.angle, audience_segment: j.audience_segment,
    script: j.script_text, visual_prompt: j.visual_prompt, word_count: j.word_count,
    provider: j.script_provider, model: j.script_model
  };
  document.getElementById('callsTitle').textContent =
    'Script JSON — job #' + jobId + (j.video_id ? ' · video #' + j.video_id : '');
  document.getElementById('callsBody').innerHTML =
    `<div class="muted">This is the script the video was generated from.</div>
     <pre style="background:#0b0e14;border:1px solid var(--line);border-radius:8px;padding:12px;white-space:pre-wrap;word-break:break-word">${esc(JSON.stringify(obj,null,2))}</pre>`;
  document.getElementById('callsModal').classList.add('show');
}

/* ---------- Per-video API call history ---------- */
function closeCalls(){ document.getElementById('callsModal').classList.remove('show'); }
async function showCalls(videoId){
  const body = document.getElementById('callsBody');
  document.getElementById('callsTitle').textContent = 'API call history — video #' + videoId;
  body.innerHTML = '<div class="muted">Loading…</div>';
  document.getElementById('callsModal').classList.add('show');
  try {
    const calls = await fetch('/api/videos/'+videoId+'/calls').then(r=>r.json());
    if(!calls.length){ body.innerHTML = '<div class="empty">No API calls recorded for this video.</div>'; return; }
    body.innerHTML = calls.map(c=>{
      const isScript = c.method==='SCRIPT';
      const code = c.status_code!=null ? ` · <span class="muted">HTTP ${c.status_code}</span>` : '';
      const reqLabel = isScript ? 'script object (fed into the payload)' : 'request';
      const req = c.request_payload!=null ? `<div class="muted">${reqLabel}</div><pre>${esc(JSON.stringify(c.request_payload,null,2))}</pre>` : '';
      const res = c.response_body!=null ? `<div class="muted">response</div><pre>${esc(JSON.stringify(c.response_body,null,2))}</pre>` : '';
      const methStyle = isScript ? ' style="color:var(--green)"' : '';
      return `<div class="callcard"${isScript?' style="border-color:rgba(46,204,113,.4)"':''}><div class="hd"><span class="meth"${methStyle}>${esc(c.method)}</span>
        <span>${esc(c.endpoint)}</span>${code}
        <span class="muted" style="margin-left:auto">${esc(c.provider)} · #${c.seq}</span></div>${req}${res}</div>`;
    }).join('');
  } catch(e){ body.innerHTML = '<div class="empty">Failed to load API calls.</div>'; }
}

/* ---------- Strategy Brain tab ---------- */
function renderStrategy(items){
  if(!items.length){ document.getElementById('strategyWrap').innerHTML='<div class="empty">No strategy data yet — generated scripts and metrics will appear here.</div>'; return; }
  document.getElementById('strategyWrap').innerHTML = items.map(it=>{
    const perf = rows => rows.length
      ? `<table><tr><th>${rows===it.angle_performance?'Angle':'Hook'}</th><th>Ads</th><th>CTR</th><th>ROAS</th><th>Score</th></tr>`
        + rows.map(r=>`<tr><td>${esc(r.key)}</td><td>${r.count}</td><td>${fmtPct(r.avg_ctr)}</td>
            <td>${r.avg_roas.toFixed(2)}</td><td>${r.score.toFixed(4)}</td></tr>`).join('') + `</table>`
      : '<div class="muted" style="margin-bottom:12px">No performance data yet — measure live ads.</div>';
    const avoid = [].concat(
      it.overused_angles.map(a=>`<span class="chip">angle:${esc(a)}</span>`),
      it.overused_hooks.map(h=>`<span class="chip">hook:${esc(h)}</span>`),
      it.recent_failure_codes.map(c=>`<span class="chip bad">${esc(c)}</span>`));
    return `<div class="sbcard"><h3>${esc(it.product_name)}</h3>
      <div class="muted" style="margin-bottom:10px">${it.scripts_count} script(s) generated · ranked by CTR×ROAS</div>
      <div class="muted" style="font-size:12px;text-transform:uppercase">Angle performance</div>${perf(it.angle_performance)}
      <div class="muted" style="font-size:12px;text-transform:uppercase">Hook performance</div>${perf(it.hook_performance)}
      <div class="muted" style="font-size:12px;text-transform:uppercase;margin-top:6px">Strategist will avoid</div>
      <div style="margin-top:6px">${avoid.length?avoid.join(''):'<span class="muted">nothing yet</span>'}</div></div>`;
  }).join('');
}

async function runMonitoring(){
  const b=document.getElementById('monBtn'); b.disabled=true; b.textContent='Running…';
  try{ const r=await fetch('/monitoring/run',{method:'POST'}).then(r=>r.json());
    toast(`Monitoring: evaluated ${r.evaluated}, paused ${r.paused}, errors ${r.errors}`); await load();
  }catch(e){ toast('Monitoring failed: '+e.message);} finally { b.disabled=false; b.textContent='Run monitoring now'; }
}

load();
setInterval(load, 60000);
</script>
</body>
</html>
"""
