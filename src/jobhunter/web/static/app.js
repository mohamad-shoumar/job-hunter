"use strict";
// Job hunter: one page over the local JSON API (src/jobhunter/web/app.py).
// Nothing is sent from here without a click on Send, and every change request
// carries the token the server put into the page.

const TOKEN = document.querySelector('meta[name="jh-token"]').content;
const state = { expanded: new Set(), tab: "today", view: "shortlisted", q: "", yoe: "", days: "0", jobs: [], jobId: null, detail: null, status: null };

// --- helpers -------------------------------------------------------------------

async function api(path, { method = "GET", body } = {}) {
  const opts = { method, headers: {} };
  if (method !== "GET") {
    opts.headers["Content-Type"] = "application/json";
    opts.headers["X-JH-Token"] = TOKEN;
    opts.body = JSON.stringify(body || {});
  }
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || data.detail || res.statusText);
    err.status = res.status;
    err.confirm = data.confirm;
    throw err;
  }
  return data;
}

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const $ = (sel, root = document) => root.querySelector(sel);

function toast(text, bad = false) {
  const el = document.createElement("div");
  el.className = "toast" + (bad ? " bad" : "");
  el.textContent = text;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), bad ? 7000 : 3500);
}

function day(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d) ? String(iso).slice(0, 10) : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
function dayTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
function ago(iso) {
  if (!iso) return "";
  const days = Math.round((Date.now() - new Date(iso)) / 86400000);
  return days <= 0 ? "today" : days === 1 ? "yesterday" : `${days} days ago`;
}

const STAGE_CHIP = { new: "", saved: "info", reached_out: "info", replied: "good", interviewing: "good", offer: "good", closed: "" };
function stageLabel(stage, reason) {
  const labels = state.status?.stage_labels || {};
  return (labels[stage] || stage) + (stage === "closed" && reason ? ` (${reason})` : "");
}
function stageChip(stage, reason, skipReason) {
  if (!stage || stage === "new") return "";
  const why = reason === "skipped" && skipReason ? `: ${(state.status?.skip_reasons || {})[skipReason] || skipReason}` : "";
  return `<span class="chip ${STAGE_CHIP[stage] || ""}">${esc(stageLabel(stage, reason))}${esc(why)}</span>`;
}
// The AI fit grade (sorting only): 1-5, its one-sentence reason on hover.
function gradeChip(g) {
  if (!g) return "";
  const tone = g.grade >= 4 ? "good" : g.grade <= 2 ? "warn" : "";
  return `<span class="chip ${tone}" title="${esc(g.reason)}">grade ${g.grade}/5</span>`;
}
const companyKey = (r) => (r.company || "").trim().toLowerCase() || `#${r.id}`;
// The two Jobs tab views that show one box per company: the jobs still waiting for a decision.
const GROUPED_VIEWS = new Set(["shortlisted", "visa_list"]);

// A job with no grade yet sorts in the middle (3), as on the server (fitgrade.UNGRADED).
// One board fetch can bring a whole company at once (17 Palantir London roles on 2026-10-21, 15 at
// Deliveroo on 2026-11-13): a company's jobs are grouped, best first (grade, then fit), and shown
// under one box. Display only; every job keeps its status.
// `order` sorts the companies by their best job; without it they keep the grade order.
function byCompany(rows, grade, order) {
  const groups = new Map();
  [...rows].sort((a, b) => (grade(b) || 3) - (grade(a) || 3) || (b.fit ?? b.fit_score ?? 0) - (a.fit ?? a.fit_score ?? 0))
    .forEach((r) => {
      const key = companyKey(r);
      groups.has(key) ? groups.get(key).push(r) : groups.set(key, [r]);
    });
  const list = [...groups.values()];
  if (order) list.sort(([a], [b]) => order(a, b));
  return list;
}
// The same grouping as a flat list, for the places that draw plain rows (Today).
function onePerCompany(rows, grade, order) {
  return byCompany(rows, grade, order).flatMap(([best, ...others]) => [
    { ...best, _key: companyKey(best), _more: others.length },
    ...(state.expanded.has(companyKey(best)) ? others : []),
  ]);
}
function moreButton(r) {
  if (!r._more) return "";
  const open = state.expanded.has(r._key);
  return `<button class="btn small" data-more="${esc(r._key)}">${open ? "Hide" : `+${r._more}`} more at ${esc(r.company)}</button>`;
}
// One company, one box: its best job, a badge counting the others, and the others when you press it,
// so a company that posted ten roles takes one place in the list and you choose from inside it
// (the user's call, 2026-11-14). A company with one job is drawn as before, with no box around it.
function companyBox(jobs, drawRow) {
  const [best, ...others] = jobs;
  if (!others.length) return drawRow(best);
  const key = companyKey(best);
  const open = state.expanded.has(key);
  const roles = (n) => `role${n > 1 ? "s" : ""} at ${best.company}`;
  const label = open ? `Hide ${jobs.length} ${roles(jobs.length)}` : `${others.length} more ${roles(others.length)}`;
  return `<div class="company-box ${open ? "open" : ""}">
    ${(open ? jobs : [best]).map(drawRow).join("")}
    <button class="btn small company-more" data-more="${esc(key)}">
      <span class="caret">${open ? "&#9652;" : "&#9662;"}</span> ${esc(label)}
    </button>
  </div>`;
}
// Why you skip a job: one tap, plus an optional note. The fit grade learns from these.
function skipPicker(id) {
  const reasons = Object.entries(state.status?.skip_reasons || {});
  return `<div class="skip-picker" data-skip-job="${id}">
    <div class="small muted">Why skip it? The fit grade learns from this.</div>
    <input class="skip-note" placeholder="In your own words (optional), then pick a reason or press Enter">
    <div class="row">${reasons.map(([key, label]) => `<button class="btn small" data-skip-reason="${key}">${esc(label)}</button>`).join("")}</div>
  </div>`;
}
// Skip pressed again (or Enter) with a note typed skips it as "Other"; with no note it closes the picker.
function toggleSkipPicker(anchor, id) {
  const open = anchor.parentElement.querySelector(`.skip-picker[data-skip-job="${id}"]`);
  if (open) return open.querySelector(".skip-note")?.value.trim() ? submitSkip(open, "other", anchor) : open.remove();
  anchor.insertAdjacentHTML("afterend", skipPicker(id));
  anchor.parentElement.querySelector(".skip-note")?.focus();
}
async function submitSkip(picker, reason, button) {
  const id = Number(picker.dataset.skipJob);
  const detail = await busy(button, "…", () => api(`/api/jobs/${id}/stage`, {
    method: "POST", body: { stage: "closed", reason: "skipped", skip_reason: reason, skip_note: picker.querySelector(".skip-note")?.value || "" },
  }));
  const message = `Skipped: ${(state.status?.skip_reasons || {})[reason] || reason}`;
  if (state.jobId === id && $("#drawer").contains(picker)) return setDetail(detail, message);
  toast(message);
  return render();
}
function statusChip(status, eligibility) {
  if (status === "shortlisted") return `<span class="chip good">shortlisted · ${esc(eligibility)}</span>`;
  if (status === "visa_list") return `<span class="chip info">visa list · ${esc(eligibility === "visa_sponsor" ? "sponsors visas" : eligibility)}</span>`;
  return `<span class="chip bad">${esc(status)}</span>`;
}

async function busy(button, label, fn) {
  const old = button ? button.textContent : "";
  if (button) { button.disabled = true; button.textContent = label; }
  try { return await fn(); } catch (err) { toast(err.message, true); throw err; }
  finally { if (button) { button.disabled = false; button.textContent = old; } }
}

// --- top bar -------------------------------------------------------------------

async function loadStatus() {
  state.status = await api("/api/status");
  const s = state.status;
  const chip = (ok, text, tip) => `<span class="chip ${ok ? "good" : "warn"}" title="${esc(tip)}">${esc(text)}</span>`;
  $("#status").innerHTML = [
    chip(s.hunter, s.hunter ? "Hunter" : "no Hunter key", s.hunter ? "HUNTER_API_KEY set" : "Add HUNTER_API_KEY to .env to find contacts"),
    chip(s.drafts, s.drafts ? `Drafts: ${s.draft_model}` : "no drafts", s.drafts ? "Email drafts are on" : `Add the key for ${s.draft_model} to .env (DEEPSEEK_API_KEY or ANTHROPIC_API_KEY)`),
    chip(s.gmail, s.gmail ? `Gmail: ${s.gmail_address}` : "Gmail not set up", s.gmail ? "Sends from this address" : "Add GMAIL_ADDRESS and GMAIL_APP_PASSWORD to .env"),
    `<span class="chip" title="Emails sent today (tests don't count)">${s.sends_today.total}/${s.caps.total} today</span>`,
  ].join("");
}

// --- routing -------------------------------------------------------------------

function route() {
  const [tab, id] = (location.hash.slice(1) || "today").split("/");
  state.tab = ["today", "jobs", "pipeline", "stats"].includes(tab) ? tab : "today";
  document.querySelectorAll("#tabs a").forEach((a) => a.classList.toggle("active", a.dataset.tab === state.tab));
  render();
  const jobId = id ? Number(id) : null;
  if (jobId && jobId !== state.jobId) openJob(jobId, false);
  if (!jobId && state.jobId) closeDrawer(false);
}

function render() {
  ({ today: renderToday, jobs: renderJobs, pipeline: renderPipeline, stats: renderStats })[state.tab]();
}

// --- jobs ----------------------------------------------------------------------

async function renderJobs() {
  const main = $("#main");
  if (!$("#jobs-list")) {
    main.innerHTML = `
      <div class="filters">
        <select id="view">
          <option value="shortlisted">Shortlisted (not acted on yet)</option>
          <option value="visa_list">Visa list (EU/UK, sponsors visas, not acted on yet)</option>
          <option value="tracked">Tracked (saved and after)</option>
          <option value="linkedin_waiting">LinkedIn: accepted, waiting on you</option>
          <option value="closed">Closed</option>
          <option value="rejected">Rejected (in a report)</option>
        </select>
        <select id="yoe" title="Years of experience the posting asks for">
          <option value="">Any years asked</option>
          <option value="lt3">Under 3 years</option>
          <option value="3-4">3 to 4 years</option>
          <option value="4-5">4 to 5 years</option>
          <option value="5+">5+ years</option>
          <option value="none">Years not mentioned</option>
        </select>
        <select id="days" title="When the job was posted (or found, if the site gives no date)">
          <option value="0">Posted any time</option>
          <option value="1">Posted today</option>
          <option value="3">Posted in the last 3 days</option>
          <option value="7">Posted in the last 7 days</option>
          <option value="14">Posted in the last 14 days</option>
          <option value="30">Posted in the last 30 days</option>
        </select>
        <input type="search" id="q" placeholder="Search title or company">
      </div>
      <div class="list" id="jobs-list"><div class="empty">Loading…</div></div>`;
    $("#view").value = state.view;
    $("#q").value = state.q;
    $("#yoe").value = state.yoe;
    $("#days").value = state.days;
    $("#view").addEventListener("change", (e) => { state.view = e.target.value; loadJobs(); });
    $("#yoe").addEventListener("change", (e) => { state.yoe = e.target.value; loadJobs(); });
    $("#days").addEventListener("change", (e) => { state.days = e.target.value; loadJobs(); });
    let timer;
    $("#q").addEventListener("input", (e) => { clearTimeout(timer); timer = setTimeout(() => { state.q = e.target.value; loadJobs(); }, 250); });
  }
  await loadJobs();
}

async function loadJobs() {
  const query = new URLSearchParams({ view: state.view, q: state.q, yoe: state.yoe, days: state.days });
  const data = await api(`/api/jobs?${query}`);
  state.jobs = data.jobs;
  const list = $("#jobs-list");
  if (!list) return;
  if (!data.jobs.length) {
    const filtered = state.yoe || state.days !== "0" || state.q;
    list.innerHTML = `<div class="empty">${filtered ? "No jobs match these filters." : "No jobs here."}</div>`;
    return;
  }
  // Only the two lists of jobs still waiting are grouped. Tracked, Closed, Rejected and the LinkedIn
  // follow-ups are lists of jobs you are already working: each row has to stand on its own there, and
  // a second one at the same company must never sit behind a button.
  if (!GROUPED_VIEWS.has(state.view)) {
    let day = null;
    list.innerHTML = data.jobs.map((j) => {
      const d = j.report_date || (j.first_seen || "").slice(0, 10);
      const head = d !== day ? `<div class="day-head">${esc(d)}</div>` : "";
      day = d;
      return head + jobRow(j);
    }).join("");
    return;
  }
  // The server's order decides where a company sits (its first row's place in the list); its own jobs
  // are then grouped into one box under that day, each row still showing its own date.
  const place = new Map();
  data.jobs.forEach((j, i) => place.has(companyKey(j)) || place.set(companyKey(j), i));
  const groups = byCompany(data.jobs, (j) => j.fit_grade?.grade,
    (a, b) => place.get(companyKey(a)) - place.get(companyKey(b)));
  let lastDay = null;
  list.innerHTML = groups.map((jobs) => {
    const d = jobs[0].report_date || (jobs[0].first_seen || "").slice(0, 10);
    const head = d !== lastDay ? `<div class="day-head">${esc(d)}</div>` : "";
    lastDay = d;
    return head + companyBox(jobs, jobRow);
  }).join("");
}

function linkedinWaitingChip(j) {
  if (!j.linkedin_accepted_at || j.linkedin_replied_at) return "";
  return `<span class="chip warn">accepted · follow up</span>`;
}

function linkedinChip(j) {
  if (j.job_board) return `<span class="chip">job board: apply via link</span>`;
  return j.linkedin ? `<span class="chip info">LinkedIn note</span>` : "";
}

function jobRow(j) {
  return `
    <div class="job-row ${state.jobId === j.id ? "selected" : ""}" data-open="${j.id}">
      <div>
        <div class="job-title">${esc(j.title)}</div>
        <div class="muted">${esc(j.company)} · <span class="small">${esc(j.reason)}</span></div>
        <div class="job-meta" style="margin-top:4px">${statusChip(j.status, j.eligibility)} ${stageChip(j.stage, j.closed_reason, j.skip_reason)} ${linkedinChip(j)} ${linkedinWaitingChip(j)}
          ${j.has_cv ? `<span class="chip">CV tailored</span>` : ""}${j.has_cover ? ` <span class="chip">cover letter</span>` : ""}</div>
      </div>
      <div class="job-side">
        ${gradeChip(j.fit_grade)}
        <span class="chip" title="Fit score from your skills">fit ${j.fit}</span>
        ${j.required_yoe ? `<span class="small" title="Years of experience the posting asks for">${j.required_yoe}+ yrs</span>` : ""}
        ${j.salary ? `<span class="small">${esc(j.salary)}</span>` : ""}
        <span class="small muted">${j.posted_at ? "posted " + esc(day(j.posted_at)) : "found " + esc(day(j.first_seen))}</span>
      </div>
    </div>`;
}

// --- job drawer ------------------------------------------------------------------

async function openJob(id, push = true) {
  state.jobId = id;
  if (push) history.replaceState(null, "", `#${state.tab}/${id}`);
  $("#drawer").hidden = false;
  $("#scrim").hidden = false;
  $("#drawer-body").innerHTML = `<div class="empty">Loading…</div>`;
  document.querySelectorAll(".job-row").forEach((r) => r.classList.toggle("selected", Number(r.dataset.open) === id));
  try {
    state.detail = await api(`/api/jobs/${id}`);
    renderDrawer();
  } catch (err) {
    $("#drawer-body").innerHTML = `<div class="empty">${esc(err.message)}</div>`;
  }
}

function closeDrawer(push = true) {
  if (state.cvEdit?.dirty && !confirm("Discard your unsaved CV edits?")) return;
  state.cvEdit = null;
  state.jobId = null;
  state.detail = null;
  $("#drawer").hidden = true;
  $("#scrim").hidden = true;
  if (push) history.replaceState(null, "", `#${state.tab}`);
  document.querySelectorAll(".job-row.selected").forEach((r) => r.classList.remove("selected"));
}

function setDetail(detail, message) {
  state.detail = detail;
  renderDrawer();
  if (message) toast(message);
  refreshInBackground();
}

function refreshInBackground() {
  loadStatus().catch(() => {});
  if (state.tab === "jobs") loadJobs().catch(() => {});
  else if (state.tab !== "stats") render();
}

function renderDrawer() {
  const d = state.detail;
  const j = d.job, app = d.application || {}, co = d.company;
  const stage = app.stage || "new";
  $("#drawer-body").innerHTML = `
    <div class="drawer-head">
      <div class="grow">
        <h2>${esc(j.title)}</h2>
        <div class="muted">${esc(co.name)} · job #${j.id}</div>
        <div class="job-meta" style="margin-top:6px">${statusChip(j.status, j.eligibility)} ${stageChip(stage, app.closed_reason, app.skip_reason)}
          ${gradeChip(j.fit_grade)} <span class="chip">fit ${j.fit}</span></div>
      </div>
      <button class="btn" data-action="close" title="Close (Esc)">✕</button>
    </div>
    <div class="row" style="margin-bottom:12px">
      <a class="btn primary" href="${esc(j.apply_url)}" target="_blank" rel="noopener">Open posting ↗</a>
      ${stage === "new" ? `<button class="btn" data-action="stage" data-stage="saved">Save</button>` : ""}
      ${app.applied_at ? `<button class="btn" data-action="applied" data-value="0">Applied ${esc(day(app.applied_at))} ✓</button>`
        : `<button class="btn" data-action="applied" data-value="1">Mark applied</button>`}
      ${stage !== "closed" ? `<button class="btn danger" data-action="stage" data-stage="closed" data-reason="skipped">Skip</button>` : ""}
    </div>
    ${cvSection(d)}
    ${coverSection(d)}
    ${linkedinSection(d)}
    ${trackingSection(d)}
    ${whySection(d)}
    <div class="section"><details><summary>Job description</summary><div class="description" style="margin-top:8px">${esc(j.description || "(none)")}</div></details></div>`;
}

function whySection(d) {
  const j = d.job;
  const details = [
    ["Remote", j.remote_status], ["Location", j.location], ["Type", j.employment_type],
    ["Salary", j.salary], ["Experience", j.required_yoe ? `${j.required_yoe}+ years asked` : ""],
    ["Posted", j.posted_at ? `${day(j.posted_at)} (${ago(j.posted_at)})` : ""], ["Found", day(j.first_seen)],
  ].filter(([, v]) => v);
  const ai = j.ai_check;
  return `
    <div class="section">
      <h3>Why it's here</h3>
      <div><b>${j.status === "visa_list" ? "Visa" : "Can hire from Lebanon"}: ${esc(j.eligibility)}</b></div>
      <ul class="small">${j.eligibility_reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
      ${ai ? `<div class="small"><b>AI check:</b> ${esc(ai.verdict)}${ai.verified ? "" : " (quote not verified)"} · ${esc(ai.reason)}
        ${ai.quote ? `<div class="quote">“${esc(ai.quote)}” ${ai.source_url ? `<a href="${esc(ai.source_url)}" target="_blank" rel="noopener">source</a>` : ""}</div>` : ""}</div>` : ""}
      ${j.fit_grade ? `<div style="margin-top:6px"><b>Fit grade ${j.fit_grade.grade}/5</b> <span class="small muted">${esc(j.fit_grade.reason)} (${esc(j.fit_grade.model)}, from your Applied and skipped jobs)</span></div>` : ""}
      <div style="margin-top:6px"><b>Fit ${j.fit}</b> <span class="small muted">${esc(j.relevance_reasons.join("; "))}</span></div>
      <div class="small muted">${esc(j.skills.join(", "))}</div>
      <div class="kv small" style="margin-top:8px">${details.map(([k, v]) => `<div>${esc(k)}</div><div>${esc(v)}</div>`).join("")}</div>
      <div class="small" style="margin-top:6px">Seen on: ${j.seen_on.map((s) => `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.source)}</a>`).join(", ")}</div>
    </div>`;
}

function cvLink(file, label = "View ↗") {
  return `<a class="btn small" href="/api/cv/${encodeURIComponent(file)}" target="_blank" rel="noopener" title="Open the PDF">${esc(label)}</a>`;
}

function cvDownload(file) {
  return `<a class="btn small" href="/api/cv/${encodeURIComponent(file)}?download=1" download="${esc(file)}" title="Save the PDF to your Downloads">Download ↓</a>`;
}

function cvSection(d) {
  const cv = d.cv, t = cv.tailored, s = state.status || {};
  const note = s.cv_tailor_note;
  const info = t ? `
      <div class="small muted" style="margin-top:6px">Tailored ${esc(ago(t.written_at))} by ${esc(t.model)}${t.cost_usd ? `, $${t.cost_usd.toFixed(3)}` : ""}
        · headline “${esc(t.headline)}” · ${t.pages} page${t.pages === 1 ? "" : "s"} · <span class="mono">${esc(t.source)}</span>
        ${t.edited_at ? ` · <b>edited by you ${esc(ago(t.edited_at))}</b>` : ""}
        ${t.file !== cv.file ? ` · ${cvLink(t.file, "View tailored ↗")}` : ""}</div>
      ${t.changes.length ? `<ul class="small">${t.changes.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>` : ""}
      ${t.notes.length ? `<div class="warnings">Code changed these:<ul>${t.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul></div>` : ""}
      ${t.gaps.length ? `<div class="small" style="margin-top:6px">The posting asks for <b>${esc(t.gaps.join(", "))}</b>: not in your profile, so not on the CV.</div>` : ""}` : "";
  return `
    <div class="section">
      <h3>CV</h3>
      <div class="row">
        ${cv.file ? `<span>For this job: <b>${esc(cv.file)}</b></span> ${cvLink(cv.file)} ${cvDownload(cv.file)}` : `<span class="muted">No CV${cv.options.length ? "" : ` (no PDFs in ${esc(cv.folder)})`}</span>`}
        ${cv.source && !editing(d) ? `<button class="btn small" data-action="edit-cv" title="Fix or remove a line by hand, then rebuild the PDF (no AI)">Edit CV ✎</button>` : ""}
      </div>
      ${info}
      <div class="row small" style="margin-top:8px">
        <button class="btn" data-action="tailor" ${note ? `disabled title="${esc(note)}"` : `title="${esc(s.cv_model || "")} picks and rewords your profile's bullets for this posting; code checks every line"`}>${t ? "Tailor again" : "Tailor CV to this job"}</button>
        <label class="muted">Use</label>
        <select id="cv">
          <option value="" ${!cv.chosen ? "selected" : ""}>Automatic${cv.file && !cv.chosen ? ` (${esc(cv.file)})` : ""}</option>
          ${cv.options.map((o) => `<option ${o === cv.chosen ? "selected" : ""}>${esc(o)}</option>`).join("")}
          <option value="none" ${cv.chosen === "none" ? "selected" : ""}>No CV</option>
        </select>
      </div>
      ${note ? `<div class="small muted" style="margin-top:6px">${esc(note)}</div>` : ""}
      ${editing(d) ? cvEditor() : ""}
    </div>`;
}

// The CV text editor: open for one job at a time, kept in state so a re-render keeps what you typed.
function editing(d) {
  return state.cvEdit && state.cvEdit.jobId === d.job.id;
}

function cvEditor() {
  const e = state.cvEdit;
  const checks = e.checks.length
    ? `<div class="warnings">These lines say more than your profile. Look at them first:<ul>${e.checks.map((c) => `<li>${esc(c)}</li>`).join("")}</ul></div>`
    : `<div class="small muted" style="margin-top:6px">The check found no line that says more than your profile.</div>`;
  return `
      <div style="margin-top:10px">
        <div class="small muted">Editing <span class="mono">${esc(e.source)}</span>. Delete a line, or put <span class="mono">//</span> in front of it to hide it.
          Saving rebuilds the PDF with build.py: no AI, what you save is what prints.
          To fix a line for every future CV, change it in <span class="mono">profile/master_profile.md</span> instead.</div>
        ${checks}
        <textarea id="cv-edit" class="mono" rows="24" spellcheck="false" style="margin-top:8px">${esc(e.text)}</textarea>
        <div class="row small" style="margin-top:6px">
          <button class="btn primary" data-action="save-cv">Save &amp; rebuild PDF</button>
          ${state.detail?.cv?.file ? cvDownload(state.detail.cv.file) : ""}
          <button class="btn" data-action="close-cv">${e.dirty ? "Discard changes" : "Close editor"}</button>
        </div>
      </div>`;
}

function coverSection(d) {
  const c = d.cover, s = state.status || {};
  const note = s.cover_note;
  const info = c ? `
      <div class="small muted" style="margin-top:6px">Written ${esc(ago(c.written_at))} by ${esc(c.model)}${c.cost_usd ? `, $${c.cost_usd.toFixed(3)}` : ""}
        · paragraph 1: ${c.words} words · <span class="mono">${esc(c.file)}</span></div>
      ${c.notes.length ? `<ul class="small">${c.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
      ${c.removed.length ? `<div class="warnings">Left out by the checks:<ul>${c.removed.map((r) => `<li>${esc(r)}</li>`).join("")}</ul></div>` : ""}
      ${c.warnings.length ? `<div class="warnings">Check these by eye:<ul>${c.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>` : ""}
      <div class="small muted" style="margin-top:6px">Read: ${c.pages?.length ? c.pages.map((u) => `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(u.replace(/^https:\/\//, ""))}</a>`).join(", ") : "the posting only"}</div>
      <textarea id="cover-text" rows="14" readonly style="margin-top:8px">${esc(c.text || "")}</textarea>` : "";
  return `
    <div class="section">
      <h3>Cover letter</h3>
      ${c ? "" : `<div class="muted">None yet. Paragraph 1 is why this company (from the posting and its website); paragraph 2 is your own text.</div>`}
      ${info}
      <div class="row small" style="margin-top:8px">
        <button class="btn" data-action="cover" ${note ? `disabled title="${esc(note)}"` : `title="${esc(s.cover_model || "")} writes paragraph 1 from the posting and the company's site; code checks every sentence"`}>${c ? "Write again" : "Write cover letter"}</button>
        ${c ? `<button class="btn" data-action="copy-cover">Copy</button>
        <button class="btn" data-action="download-cover" title="Save the letter as a .txt file to your Downloads">Download ↓</button>` : ""}
      </div>
      ${note ? `<div class="small muted" style="margin-top:6px">${esc(note)}</div>` : ""}
    </div>`;
}

// The one LinkedIn person for this job and the note to send them (the user's call, 2026-11-05: outreach is
// LinkedIn now, so there is no "who to contact" box, no subject line and no Send button). Both boxes are
// saved when you click away, like the tracking notes. Nothing is ever sent from here: you press Connect
// on LinkedIn yourself.
const NOTE_LIMIT = 300; // LinkedIn's own limit on a connection note

const noteCount = (note) => `${note.length}/${NOTE_LIMIT} characters${note.length > NOTE_LIMIT ? " — too long for LinkedIn" : ""}`;

// Where a job is on LinkedIn. You tick these yourself: only you know when someone accepted or wrote back.
const LINKEDIN_STEPS = [
  ["sent", "Invite sent", "linkedin_sent_at"],
  ["accepted", "Accepted", "linkedin_accepted_at"],
  ["replied", "Replied", "linkedin_replied_at"],
];

function linkedinSection(d) {
  const app = d.application || {};
  const url = app.linkedin_url || "", note = app.linkedin_note || "", followup = app.linkedin_followup || "";
  const steps = LINKEDIN_STEPS.map(([step, label, column]) => `
        <label class="small" style="margin-right:12px">
          <input type="checkbox" data-linkedin-step="${step}" ${app[column] ? "checked" : ""}>
          ${esc(label)}${app[column] ? ` <span class="muted">${esc(day(app[column]))}</span>` : ""}
        </label>`).join("");
  return `
    <div class="section">
      <h3>LinkedIn</h3>
      <div class="small">
        <a id="linkedin-open" href="${esc(url)}" target="_blank" rel="noopener" ${url ? "" : "hidden"}>Open profile ↗</a>
        <span id="linkedin-none" class="muted" ${url ? "hidden" : ""}>Nobody picked yet: paste the person's profile link.</span>
      </div>
      <input type="text" id="linkedin-url" value="${esc(url)}" placeholder="https://www.linkedin.com/in/…" style="margin-top:6px">
      <textarea id="linkedin-note" rows="6" style="margin-top:6px" placeholder="The note to send with the request">${esc(note)}</textarea>
      <div class="small muted" id="note-count">${esc(noteCount(note))}</div>
      <div class="row" style="margin-top:10px">${steps}</div>
      ${followupHint(app)}
      <label class="small muted" style="margin-top:6px;display:block">After they accept — send it yourself, Tue–Thu morning their time</label>
      <textarea id="linkedin-followup" rows="4" placeholder="The message to send once they accept">${esc(followup)}</textarea>
    </div>`;
}

// The gap the first week's review found: accepted, then nothing. Shown until you tick Replied.
function followupHint(app) {
  if (!app.linkedin_accepted_at || app.linkedin_replied_at) return "";
  return `<div class="warnings" style="margin-top:8px">Accepted ${esc(ago(app.linkedin_accepted_at))} — waiting on your follow-up.</div>`;
}

function trackingSection(d) {
  const app = d.application || {};
  const stages = (state.status?.stages || []).filter((s) => s !== "new");
  const stage = app.stage || "new";
  return `
    <div class="section">
      <h3>Tracking</h3>
      <div class="row">
        <label class="small muted">Stage</label>
        <select id="stage">${["new", ...stages].map((s) => `<option value="${s}" ${s === stage ? "selected" : ""}>${esc(stageLabel(s))}</option>`).join("")}</select>
        <select id="reason" ${stage === "closed" ? "" : "hidden"}>${(state.status?.closed_reasons || []).map((r) => `<option ${r === app.closed_reason ? "selected" : ""}>${r}</option>`).join("")}</select>
        ${app.next_follow_up_at && stage === "reached_out" ? `<span class="chip ${new Date(app.next_follow_up_at) <= new Date() ? "warn" : ""}">follow-up ${esc(day(app.next_follow_up_at))}</span>` : ""}
        ${app.replied_at ? `<span class="chip good">replied ${esc(day(app.replied_at))}</span>` : ""}
      </div>
      ${app.reply_snippet ? `<div class="quote" style="margin-top:8px"><b>${esc(app.reply_from || "")}</b>: ${esc(app.reply_snippet)}</div>` : ""}
      <textarea id="notes" rows="3" style="margin-top:8px" placeholder="Notes (saved when you click away)">${esc(app.notes || "")}</textarea>
      ${d.events.length ? `<ul class="timeline" style="margin-top:8px">${d.events.slice().reverse().map((e) => `<li><span class="when">${esc(dayTime(e.at))}</span><span>${esc(e.detail)}</span></li>`).join("")}</ul>` : ""}
    </div>`;
}

// --- drawer actions ----------------------------------------------------------------

async function drawerAction(action, el) {
  const id = state.jobId;
  const d = state.detail;
  if (action === "close") return closeDrawer();
  if (action === "stage" && el.dataset.reason === "skipped") return toggleSkipPicker(el.parentElement, id);
  if (action === "stage") {
    const detail = await busy(el, "…", () => api(`/api/jobs/${id}/stage`, { method: "POST", body: { stage: el.dataset.stage, reason: el.dataset.reason } }));
    return setDetail(detail, `Moved to ${stageLabel(el.dataset.stage, el.dataset.reason)}`);
  }
  if (action === "applied") {
    const detail = await busy(el, "…", () => api(`/api/jobs/${id}/application`, { method: "PATCH", body: { applied: el.dataset.value === "1" } }));
    return setDetail(detail, el.dataset.value === "1" ? "Marked as applied" : "Applied date cleared");
  }
  if (action === "tailor") {
    const edited = Boolean(d.cv.tailored?.edited_at);
    if (edited && !confirm("You edited this CV by hand. Tailoring again replaces your edits. Go ahead?")) return;
    const detail = await busy(el, "Tailoring… (up to a minute)", () => api(`/api/jobs/${id}/tailor`, { method: "POST", body: { replace_edits: edited } }));
    state.cvEdit = null;
    const t = detail.tailored || {};
    return setDetail(detail, `CV ready: ${t.file}${t.notes?.length ? " (see what code changed)" : ""}`);
  }
  if (action === "cover") {
    if (d.cover && !confirm("Write a new cover letter? It replaces this one, including edits you made to the file.")) return;
    const detail = await busy(el, "Reading the company's site and writing… (up to a minute)", () => api(`/api/jobs/${id}/cover`, { method: "POST" }));
    return setDetail(detail, `Cover letter ready: ${detail.cover?.file}${detail.cover?.removed.length ? " (the check left some sentences out)" : ""}`);
  }
  if (action === "edit-cv") {
    const r = await busy(el, "Opening…", () => api(`/api/jobs/${id}/cv-text`));
    state.cvEdit = { jobId: id, source: r.source, text: r.text, checks: r.checks, dirty: false };
    renderDrawer();
    return $("#cv-edit")?.focus();
  }
  if (action === "save-cv") {
    const text = $("#cv-edit").value;
    const detail = await busy(el, "Rebuilding the PDF…", () => api(`/api/jobs/${id}/cv-text`, { method: "PUT", body: { text } }));
    const r = detail.cv_saved;
    state.cvEdit = { jobId: id, source: r.source, text, checks: r.checks, dirty: false };
    return setDetail(detail, `PDF rebuilt: ${r.file} (${r.pages} page${r.pages === 1 ? "" : "s"})${r.notes.length ? ". " + r.notes[0] : ""}`);
  }
  if (action === "close-cv") {
    if (state.cvEdit?.dirty && !confirm("Discard your unsaved CV edits?")) return;
    state.cvEdit = null;
    return renderDrawer();
  }
  if (action === "copy-cover") {
    await navigator.clipboard.writeText($("#cover-text").value);
    return toast("Copied");
  }
  if (action === "download-cover") {
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([$("#cover-text").value], { type: "text/plain" }));
    link.download = (state.detail?.cover?.file || "CoverLetter.md").replace(/\.md$/, ".txt");
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    return toast(`Saved ${link.download}`);
  }
}

// --- today -----------------------------------------------------------------------

async function renderToday() {
  const t = await api("/api/today");
  const item = (r, extra = "") => `<li><a data-open="${r.job_id || r.id}"><b>${esc(r.title)}</b></a> <span class="muted">· ${esc(r.company)}</span>${extra}</li>`;
  const card = (title, rows, empty) => `<div class="card"><h2>${title} <span class="muted small">${rows.length || ""}</span></h2>${rows.length ? `<ul>${rows.join("")}</ul>` : `<div class="muted">${empty}</div>`}</div>`;
  $("#main").innerHTML = `
    <div class="cards">
      ${card("Replies to answer", t.replies.map((r) => item(r, `<div class="quote">${esc(r.reply_from || "")}: ${esc(r.reply_snippet || "")}</div>`)), "No new replies. Click Check inbox to look.")}
      ${card("Follow-ups due", t.follow_ups_due.map((r) => item(r, `<div class="small muted">to ${esc(r.email || "?")} · follow-up ${r.follow_ups + 1} · due ${esc(day(r.next_follow_up_at))}</div>`)), "Nothing due.")}
      ${card("New shortlisted to triage", onePerCompany(t.new_jobs, (r) => r.fit_grade).map((r) => item(r, ` ${r.fit_grade ? `<span class="chip">grade ${r.fit_grade}/5</span>` : ""} <span class="chip">fit ${r.fit_score}</span>
        <span class="row" style="margin-top:4px"><button class="btn small" data-quick="saved" data-id="${r.id}">Save</button><button class="btn small danger" data-quick="skipped" data-id="${r.id}">Skip</button>${moreButton(r)}</span>`)), "All caught up.")}
      ${card("New on the visa list (EU/UK)", onePerCompany(t.new_visa_jobs || [], (r) => r.fit_grade).map((r) => item(r, ` ${r.fit_grade ? `<span class="chip">grade ${r.fit_grade}/5</span>` : ""} <span class="chip">fit ${r.fit_score}</span>
        <span class="row" style="margin-top:4px"><button class="btn small" data-quick="saved" data-id="${r.id}">Save</button><button class="btn small danger" data-quick="skipped" data-id="${r.id}">Skip</button>${moreButton(r)}</span>`)), "None this week.")}
      ${t.unsure_sends.length ? card("Sends to double-check", t.unsure_sends.map((r) => item(r, `<div class="small muted">Gmail didn't confirm ${esc(r.subject)}: Check inbox resolves it.</div>`)), "") : ""}
      ${card("Ghosted this week", t.ghosted.map((r) => item(r, `<div class="small muted">closed ${esc(day(r.at))}</div>`)), "None.")}
      <div class="card"><h2>Today</h2><div class="big">${t.sends_today.total}<span class="muted small"> / ${t.caps.total} emails sent</span></div>
        <div class="muted small">Guessed addresses: ${t.sends_today.guessed} / ${t.caps.guessed}. Best reply rates: Tue–Thu mornings in their time zone.</div></div>
    </div>`;
}

// --- pipeline ----------------------------------------------------------------------

// Board columns. "To apply" is shortlisted jobs you haven't acted on (stage new) or saved, plus visa-list jobs
// posted today or yesterday, newest posting first. Reached out is newest reached out first: every job there gets
// a LinkedIn note now, so there is no Email someone column (the user's call, 2026-10-29), and no Saved column.
// Rejected is back (the user's call, 2026-11-11): a rejection is the one closing you did not choose, so it has
// its own column, and Closed keeps the ones you decided (skipped) or that went quiet (ghosted). Both are the
// same stage `closed`, told apart by `closed_reason`: display only, no new stage and no migration. Moving a card
// into Rejected closes it with reason "rejected" (`reason` below), the way the inbox check does.
const BOARD = [
  { key: "to_apply", label: "To apply", stage: "new" },
  ...["reached_out", "replied", "interviewing", "offer"].map((s) => ({ key: s, stage: s })),
  { key: "rejected", label: "Rejected", stage: "closed", reason: "rejected" },
  { key: "closed", label: "Closed", stage: "closed" },
];
const toApplyStage = (j) => !j.stage || j.stage === "new" || j.stage === "saved";
function boardKey(j) {
  if (toApplyStage(j)) return "to_apply";
  return j.stage === "closed" && j.closed_reason === "rejected" ? "rejected" : j.stage;
}
// Newest first, by the local day the card shows; the same day keeps the grade order.
const localDay = (iso) => { const d = new Date(iso); return isNaN(d) ? String(iso || "").slice(0, 10) : d.toLocaleDateString("sv"); };
const newestDay = (when) => (a, b) => localDay(when(b)).localeCompare(localDay(when(a)));
const postedAt = (j) => j.posted_at || j.first_seen;
const newestReachedOut = (a, b) => (Date.parse(b.reached_out_at) || 0) - (Date.parse(a.reached_out_at) || 0);


async function renderPipeline() {
  // Rejections are asked for on their own (view=closed_rejected): the closed list stops at 500 rows and
  // hundreds of them are jobs I skipped, which would hide the oldest rejections from their column. A browser
  // that already has this file while `jobhunter serve` still runs the older code gets a 400 here: then the
  // column falls back to the rejections inside the closed list, so the board draws either way.
  const [open, visa, tracked, closed, rejected] = await Promise.all([
    api("/api/jobs?view=shortlisted"), api("/api/jobs?view=visa_list&days=2"), api("/api/jobs?view=tracked"),
    api("/api/jobs?view=closed"), api("/api/jobs?view=closed_rejected").catch(() => null),
  ]);
  const grade = (j) => j.fit_grade?.grade;
  // A saved job is in the tracked list too (and a visa-list one may be older than the two days): it shows once, in To apply.
  const waiting = [...open.jobs, ...visa.jobs].filter(toApplyStage);
  const ids = new Set(waiting.map((j) => j.id));
  // To apply is grouped: one box per company, its best job on top and the rest a press away, so a
  // board fetch that brought ten roles at one company is one choice, not ten cards (2026-11-14).
  const toApply = byCompany([...waiting, ...tracked.jobs.filter((j) => j.stage === "saved" && !ids.has(j.id))], grade, newestDay(postedAt));
  const reachedOut = tracked.jobs.filter((j) => j.stage === "reached_out").sort(newestReachedOut);
  // The closed list holds rejections too: they come from their own list instead, so no card shows twice.
  const isRejected = (j) => j.closed_reason === "rejected";
  const jobs = [...toApply.flat(), ...reachedOut, ...tracked.jobs.filter((j) => !toApplyStage(j) && j.stage !== "reached_out"),
    ...(rejected ? rejected.jobs : closed.jobs.filter(isRejected)), ...closed.jobs.filter((j) => !isRejected(j))];
  const options = (current) => BOARD
    .map((c) => `<option value="${c.key}" ${c.key === current ? "selected" : ""}>${esc(c.label || stageLabel(c.stage))}</option>`).join("");
  // The To apply column draws one box per company; every other column one card per job.
  const drawn = (col) => {
    const cards = jobs.filter((j) => boardKey(j) === col.key);
    const html = col.key === "to_apply"
      ? toApply.map((group) => companyBox(group, (j) => pcard(j, col))).join("")
      : cards.map((j) => pcard(j, col)).join("");
    return { count: cards.length, html: html || `<div class="small muted" style="margin-top:8px">Empty</div>` };
  };
  const pcard = (j, col) => `
      <div class="pcard">
        <div class="job-title" data-open="${j.id}">${esc(j.title)}</div>
        <div class="small muted">${esc(j.company)}</div>
        <div class="job-meta small" style="margin-top:4px">
          ${j.status === "visa_list" ? `<span class="chip info">visa</span>` : ""}
          ${col.key === "to_apply" ? `<span class="chip">posted ${esc(day(postedAt(j)))}</span>${gradeChip(j.fit_grade)}<span class="chip">fit ${j.fit}</span>${j.has_cv ? `<span class="chip good">CV</span>` : ""}${j.has_cover ? `<span class="chip good">letter</span>` : ""}` : ""}
          ${j.applied_at ? `<span class="chip">applied ${esc(day(j.applied_at))}</span>` : ""}${j.emailed_at ? `<span class="chip info">emailed ${esc(day(j.emailed_at))}</span>` : ""}
          ${!j.applied_at && !j.emailed_at && j.reached_out_at && col.key === "reached_out" ? `<span class="chip">reached out ${esc(day(j.reached_out_at))}</span>` : ""}
          ${j.stage === "reached_out" && j.next_follow_up_at ? `<span class="chip ${new Date(j.next_follow_up_at) <= new Date() ? "warn" : ""}">follow-up ${esc(day(j.next_follow_up_at))}</span>` : ""}
          ${j.closed_reason && col.key === "closed" ? `<span class="chip">${esc(j.closed_reason)}${j.skip_reason ? esc(": " + ((state.status?.skip_reasons || {})[j.skip_reason] || j.skip_reason)) : ""}</span>` : ""}
        </div>
        <div class="row"><select data-move="${j.id}">${options(col.key)}</select>
          ${col.key === "to_apply" ? `<button class="btn small danger" data-quick="skipped" data-id="${j.id}">Skip</button>` : ""}</div>
      </div>`;
  $("#main").innerHTML = `<div class="board">${BOARD.map((col) => {
    const { count, html } = drawn(col);
    return `<div class="column"><h3>${esc(col.label || stageLabel(col.stage))} <span>${count}</span></h3>${html}</div>`;
  }).join("")}</div>`;
}

// --- stats ----------------------------------------------------------------------------

async function renderStats() {
  const s = await api("/api/stats");
  const rate = (e) => e.emailed ? Math.round((100 * e.replied) / e.emailed) : 0;
  const table = (rows, label) => rows.length ? `<table><tr><th>${label}</th><th>Emailed</th><th>Replied</th><th>Rate</th></tr>${rows.map(([k, e]) => `
    <tr><td>${esc(k)}</td><td>${e.emailed}</td><td>${e.replied}</td><td style="min-width:120px"><div class="row"><span>${rate(e)}%</span><div class="bar grow"><span style="width:${rate(e)}%"></span></div></div></td></tr>`).join("")}</table>`
    : `<div class="muted">No emails sent yet.</div>`;
  const funnel = ["saved", "reached_out", "replied", "interviewing", "offer", "closed"];
  $("#main").innerHTML = `
    <div class="cards">
      <div class="card"><h2>Pipeline</h2><table>${funnel.map((st) => `<tr><td>${esc(stageLabel(st))}</td><td class="big" style="font-size:18px">${s.stages[st] || 0}</td></tr>`).join("")}</table>
        ${Object.keys(s.closed).length ? `<div class="small muted" style="margin-top:6px">Closed: ${Object.entries(s.closed).map(([k, v]) => `${v} ${esc(k)}`).join(", ")}</div>` : ""}</div>
      <div class="card"><h2>Outreach</h2>
        <div class="row"><div><div class="big">${s.emailed}</div><div class="small muted">emailed</div></div>
          <div><div class="big">${s.replied}</div><div class="small muted">replied</div></div>
          <div><div class="big">${s.emailed ? Math.round((100 * s.replied) / s.emailed) : 0}%</div><div class="small muted">reply rate</div></div>
          <div><div class="big">${s.bounced}</div><div class="small muted">bounced</div></div></div>
        <div class="small muted" style="margin-top:8px">${s.applied} applied through postings · ${s.sent_this_week} emails this week. Research says 5–15% replies is normal for well-targeted cold email.</div></div>
      <div class="card"><h2>Reply rate by who you emailed</h2>${table(Object.entries(s.by_role).map(([k, v]) => [s.role_labels[k] || k, v]), "Contact")}</div>
      <div class="card"><h2>Reply rate by company size</h2>${table(Object.entries(s.by_size), "People")}</div>
      <div class="card"><h2>Hunter credits</h2><div id="credits" class="muted">Checking is free.</div>
        <button class="btn" data-action-global="credits" style="margin-top:8px">Check credits</button></div>
    </div>`;
}

// --- events -----------------------------------------------------------------------------

document.addEventListener("click", async (e) => {
  const open = e.target.closest("[data-open]");
  const action = e.target.closest("[data-action]");
  const quick = e.target.closest("[data-quick]");
  const global = e.target.closest("[data-action-global]");
  try {
    const more = e.target.closest("[data-more]");
    if (more) {
      e.stopPropagation();
      const key = more.dataset.more;
      state.expanded.has(key) ? state.expanded.delete(key) : state.expanded.add(key);
      return render();
    }
    const skipReason = e.target.closest("[data-skip-reason]");
    if (skipReason) {
      e.stopPropagation();
      return await submitSkip(skipReason.closest("[data-skip-job]"), skipReason.dataset.skipReason, skipReason);
    }
    if (quick && quick.dataset.quick === "skipped") {
      e.stopPropagation();
      return await toggleSkipPicker(quick.closest(".row") || quick, quick.dataset.id);
    }
    if (quick) {
      e.stopPropagation();
      await busy(quick, "…", () => api(`/api/jobs/${quick.dataset.id}/stage`, { method: "POST", body: { stage: "saved" } }));
      toast("Saved");
      return render();
    }
    if (action && action.dataset.action === "check-inbox") {
      const r = await busy(action, "Checking…", () => api("/api/inbox/check", { method: "POST" }));
      const parts = [`${r.replies} replies`, r.probable ? `${r.probable} probable` : "", `${r.bounces} bounces`, r.auto_replies ? `${r.auto_replies} auto-replies` : "",
        r.test_replies ? `${r.test_replies} test replies` : ""].filter(Boolean);
      toast(`Inbox: ${parts.join(", ")}${r.resolved?.length ? ". " + r.resolved.join("; ") : ""}${r.notes?.length ? ". " + r.notes.join("; ") : ""}`);
      if (state.jobId) openJob(state.jobId, false);
      return render();
    }
    if (global && global.dataset.actionGlobal === "credits") {
      const s = await busy(global, "…", () => api("/api/status?credits=1"));
      const c = s.hunter_credits;
      $("#credits").textContent = c ? `${c.remaining ?? "?"} of ${c.available ?? "?"} left${c.reset_date ? `, resets ${c.reset_date}` : ""} (${c.plan || "plan"})` : "No Hunter key, or Hunter did not answer.";
      return;
    }
    if (action && $("#drawer").contains(action)) return await drawerAction(action.dataset.action, action);
    if (open) return openJob(Number(open.dataset.open));
  } catch (err) {
    if (!err.status) console.error(err);
  }
});

document.addEventListener("change", async (e) => {
  try {
    if (e.target.id === "stage" || e.target.id === "reason") {
      const stage = $("#stage").value;
      $("#reason").hidden = stage !== "closed";
      if (stage === "closed" && e.target.id === "stage") return; // pick the reason next, or keep the first
      const detail = await api(`/api/jobs/${state.jobId}/stage`, { method: "POST", body: { stage, reason: stage === "closed" ? $("#reason").value : undefined } });
      return setDetail(detail, `Moved to ${stageLabel(stage)}`);
    }
    if (e.target.id === "cv") {
      const detail = await api(`/api/jobs/${state.jobId}/application`, { method: "PATCH", body: { cv_file: e.target.value } });
      return setDetail(detail, e.target.value === "none" ? "No CV will be attached" : "CV updated");
    }
    if (e.target.matches("[data-linkedin-step]")) {
      const step = e.target.dataset.linkedinStep;
      const detail = await api(`/api/jobs/${state.jobId}/application`, { method: "PATCH", body: { [`linkedin_${step}`]: e.target.checked } });
      return setDetail(detail, e.target.checked ? `Marked ${step}` : `${step} cleared`);
    }
    if (e.target.matches("[data-move]")) {
      const col = BOARD.find((c) => c.key === e.target.value);
      const stage = col.stage;
      const reason = col.reason || (stage === "closed" ? prompt("Why closed? ghosted or skipped (a rejection goes in the Rejected column)", "skipped") : undefined);
      if (stage === "closed" && !reason) return renderPipeline();
      await api(`/api/jobs/${e.target.dataset.move}/stage`, { method: "POST", body: { stage, reason } });
      toast(`Moved to ${col.label || stageLabel(stage, reason)}`);
      return renderPipeline();
    }
  } catch (err) {
    toast(err.message, true);
  }
});

// The boxes that save themselves when you click away: the tracking notes, and the LinkedIn link and note
// (the user's call, 2026-11-05: no Save, Edit or Copy buttons on the card).
const SAVE_ON_BLUR = {
  notes: ["notes", "Notes saved"],
  "linkedin-url": ["linkedin_url", "LinkedIn profile saved"],
  "linkedin-note": ["linkedin_note", "Note saved"],
  "linkedin-followup": ["linkedin_followup", "Follow-up saved"],
};

document.addEventListener("focusout", async (e) => {
  const field = SAVE_ON_BLUR[e.target.id];
  if (!field || !state.detail) return;
  const [key, message] = field;
  const value = e.target.value;
  if (value === (state.detail.application?.[key] || "")) return;
  try {
    state.detail = await api(`/api/jobs/${state.jobId}/application`, { method: "PATCH", body: { [key]: value } });
    toast(message);
    // What the server stored, put back in place (it trims, and tidies a link into https://…), so the
    // card is never re-rendered under you while you are typing in the other box.
    const app = state.detail.application || {};
    if (key === "linkedin_note") e.target.value = app.linkedin_note || "";
    if (key === "linkedin_followup") e.target.value = app.linkedin_followup || "";
    if (key === "linkedin_url") {
      const url = app.linkedin_url || "";
      $("#linkedin-url").value = url;
      $("#linkedin-open").href = url;
      $("#linkedin-open").hidden = !url;
      $("#linkedin-none").hidden = Boolean(url);
    }
  } catch (err) { toast(err.message, true); }
});

document.addEventListener("input", (e) => {
  if (e.target.id === "linkedin-note" && $("#note-count")) $("#note-count").textContent = noteCount(e.target.value);
  if (e.target.id === "cv-edit" && state.cvEdit) {
    state.cvEdit.text = e.target.value;
    if (!state.cvEdit.dirty) {
      state.cvEdit.dirty = true;
      const close = $('[data-action="close-cv"]');
      if (close) close.textContent = "Discard changes";
    }
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && e.target.matches(".skip-note") && e.target.value.trim()) {
    e.preventDefault();
    return submitSkip(e.target.closest("[data-skip-job]"), "other").catch(() => {});
  }
  if (e.key === "Escape" && state.jobId) closeDrawer();
});
$("#scrim").addEventListener("click", () => closeDrawer());

window.addEventListener("hashchange", route);
loadStatus().then(route).catch((err) => { $("#main").innerHTML = `<div class="empty">${esc(err.message)}</div>`; });
