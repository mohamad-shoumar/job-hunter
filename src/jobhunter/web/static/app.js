"use strict";
// Job hunter: one page over the local JSON API (src/jobhunter/web/app.py).
// Nothing is sent from here without a click on Send, and every change request
// carries the token the server put into the page.

const TOKEN = document.querySelector('meta[name="jh-token"]').content;
const state = { tab: "today", view: "shortlisted", q: "", jobs: [], jobId: null, detail: null, status: null };

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
function stageChip(stage, reason) {
  if (!stage || stage === "new") return "";
  return `<span class="chip ${STAGE_CHIP[stage] || ""}">${esc(stageLabel(stage, reason))}</span>`;
}
const EMAIL_BADGE = {
  verified: ["good", "verified"], manual: ["good", "added by you"], found: ["info", "found (not verified)"],
  accept_all: ["warn", "accept-all: can't be checked"], guessed: ["warn", "guessed"], bounced: ["bad", "bounced"],
  invalid: ["bad", "invalid"],
};
function emailBadge(status) {
  if (!status) return `<span class="chip">no email</span>`;
  const [cls, text] = EMAIL_BADGE[status] || ["", status];
  return `<span class="chip ${cls}">${esc(text)}</span>`;
}
function statusChip(status, eligibility) {
  if (status === "shortlisted") return `<span class="chip good">shortlisted · ${esc(eligibility)}</span>`;
  if (status === "needs_review") return `<span class="chip warn">needs review</span>`;
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
          <option value="shortlisted">Shortlisted</option>
          <option value="active">Shortlisted + needs review</option>
          <option value="needs_review">Needs review</option>
          <option value="tracked">Tracked (saved and after)</option>
          <option value="closed">Closed</option>
          <option value="rejected">Rejected (in a report)</option>
        </select>
        <input type="search" id="q" placeholder="Search title or company">
      </div>
      <div class="list" id="jobs-list"><div class="empty">Loading…</div></div>`;
    $("#view").value = state.view;
    $("#q").value = state.q;
    $("#view").addEventListener("change", (e) => { state.view = e.target.value; loadJobs(); });
    let timer;
    $("#q").addEventListener("input", (e) => { clearTimeout(timer); timer = setTimeout(() => { state.q = e.target.value; loadJobs(); }, 250); });
  }
  await loadJobs();
}

async function loadJobs() {
  const data = await api(`/api/jobs?view=${encodeURIComponent(state.view)}&q=${encodeURIComponent(state.q)}`);
  state.jobs = data.jobs;
  const list = $("#jobs-list");
  if (!list) return;
  if (!data.jobs.length) { list.innerHTML = `<div class="empty">No jobs here.</div>`; return; }
  let lastDay = null;
  list.innerHTML = data.jobs.map((j) => {
    const d = j.report_date || (j.first_seen || "").slice(0, 10);
    const head = d !== lastDay ? `<div class="day-head">${esc(d)}</div>` : "";
    lastDay = d;
    return head + jobRow(j);
  }).join("");
}

function contactChip(j) {
  if (j.job_board) return `<span class="chip">job board: apply via link</span>`;
  if (!j.contact) return `<span class="chip">no contact yet</span>`;
  return `<span class="chip ${j.contact.email_status === "bounced" ? "bad" : "info"}">${esc(j.contact.role)}: ${esc(j.contact.name)}</span>` +
    (j.contact.email_status ? emailBadge(j.contact.email_status) : "");
}

function jobRow(j) {
  return `
    <div class="job-row ${state.jobId === j.id ? "selected" : ""}" data-open="${j.id}">
      <div>
        <div class="job-title">${esc(j.title)}</div>
        <div class="muted">${esc(j.company)} · <span class="small">${esc(j.reason)}</span></div>
        <div class="job-meta" style="margin-top:4px">${statusChip(j.status, j.eligibility)} ${stageChip(j.stage, j.closed_reason)} ${contactChip(j)}
          ${j.has_draft ? `<span class="chip ${j.draft_blocked ? "bad" : ""}">${j.draft_blocked ? "draft needs edit" : "draft ready"}</span>` : ""}
          ${j.has_cv ? `<span class="chip">CV tailored</span>` : ""}${j.has_cover ? ` <span class="chip">cover letter</span>` : ""}</div>
      </div>
      <div class="job-side">
        <span class="chip" title="Fit score from your skills">fit ${j.fit}</span>
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
        <div class="job-meta" style="margin-top:6px">${statusChip(j.status, j.eligibility)} ${stageChip(stage, app.closed_reason)}
          <span class="chip">fit ${j.fit}</span></div>
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
    ${contactSection(d)}
    ${emailSection(d)}
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
      <div><b>Can hire from Lebanon: ${esc(j.eligibility)}</b></div>
      <ul class="small">${j.eligibility_reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
      ${ai ? `<div class="small"><b>AI check:</b> ${esc(ai.verdict)}${ai.verified ? "" : " (quote not verified)"} · ${esc(ai.reason)}
        ${ai.quote ? `<div class="quote">“${esc(ai.quote)}” ${ai.source_url ? `<a href="${esc(ai.source_url)}" target="_blank" rel="noopener">source</a>` : ""}</div>` : ""}</div>` : ""}
      <div style="margin-top:6px"><b>Fit ${j.fit}</b> <span class="small muted">${esc(j.relevance_reasons.join("; "))}</span></div>
      <div class="small muted">${esc(j.skills.join(", "))}</div>
      <div class="kv small" style="margin-top:8px">${details.map(([k, v]) => `<div>${esc(k)}</div><div>${esc(v)}</div>`).join("")}</div>
      <div class="small" style="margin-top:6px">Seen on: ${j.seen_on.map((s) => `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.source)}</a>`).join(", ")}</div>
    </div>`;
}

function cvLink(file, label = "View ↗") {
  return `<a class="btn small" href="/api/cv/${encodeURIComponent(file)}" target="_blank" rel="noopener" title="Open the PDF">${esc(label)}</a>`;
}

function cvSection(d) {
  const cv = d.cv, t = cv.tailored, s = state.status || {};
  const note = s.cv_tailor_note;
  const info = t ? `
      <div class="small muted" style="margin-top:6px">Tailored ${esc(ago(t.written_at))} by ${esc(t.model)}${t.cost_usd ? `, $${t.cost_usd.toFixed(3)}` : ""}
        · headline “${esc(t.headline)}” · ${t.pages} page${t.pages === 1 ? "" : "s"} · <span class="mono">${esc(t.source)}</span>
        ${t.file !== cv.file ? ` · ${cvLink(t.file, "View tailored ↗")}` : ""}</div>
      ${t.changes.length ? `<ul class="small">${t.changes.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>` : ""}
      ${t.notes.length ? `<div class="warnings">Code changed these:<ul>${t.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul></div>` : ""}
      ${t.gaps.length ? `<div class="small" style="margin-top:6px">The posting asks for <b>${esc(t.gaps.join(", "))}</b>: not in your profile, so not on the CV.</div>` : ""}` : "";
  return `
    <div class="section">
      <h3>CV</h3>
      <div class="row">
        ${cv.file ? `<span>For this job: <b>${esc(cv.file)}</b></span> ${cvLink(cv.file)}` : `<span class="muted">No CV${cv.options.length ? "" : ` (no PDFs in ${esc(cv.folder)})`}</span>`}
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
    </div>`;
}

function coverSection(d) {
  const c = d.cover, s = state.status || {};
  const note = s.cover_note;
  const info = c ? `
      <div class="small muted" style="margin-top:6px">Written ${esc(ago(c.written_at))} by ${esc(c.model)}${c.cost_usd ? `, $${c.cost_usd.toFixed(3)}` : ""}
        · ${c.words} words · <span class="mono">${esc(c.file)}</span></div>
      ${c.notes.length ? `<ul class="small">${c.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
      ${c.removed.length ? `<div class="warnings">Left out by the fact check:<ul>${c.removed.map((r) => `<li>${esc(r)}</li>`).join("")}</ul></div>` : ""}
      ${c.warnings.length ? `<div class="warnings">Check these by eye:<ul>${c.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>` : ""}
      ${c.gaps_named.length ? `<div class="small" style="margin-top:6px">It says you have not worked with <b>${esc(c.gaps_named.join(", "))}</b>.</div>` : ""}
      <textarea id="cover-text" rows="14" readonly style="margin-top:8px">${esc(c.text || "")}</textarea>` : "";
  return `
    <div class="section">
      <h3>Cover letter</h3>
      ${c ? "" : `<div class="muted">None yet. It uses only the facts your CV prints for this job.</div>`}
      ${info}
      <div class="row small" style="margin-top:8px">
        <button class="btn" data-action="cover" ${note ? `disabled title="${esc(note)}"` : `title="${esc(s.cover_model || "")} writes it from your profile facts; code checks every sentence"`}>${c ? "Write again" : "Write cover letter"}</button>
        ${c ? `<button class="btn" data-action="copy-cover">Copy</button>` : ""}
      </div>
      ${note ? `<div class="small muted" style="margin-top:6px">${esc(note)}</div>` : ""}
    </div>`;
}

function contactSection(d) {
  const co = d.company, c = d.contact;
  const s = state.status || {};
  if (co.is_job_board || co.skip_listed) {
    return `
      <div class="section">
        <h3>Who to contact</h3>
        <p>${esc(co.name)} is a job board or agency, so there is nobody to pitch: apply through the posting.</p>
        ${co.skip_listed ? `<p class="small muted">On the skip list in config/outreach.json.</p>`
          : `<button class="btn small" data-action="job-board" data-value="0">It's a real employer</button>`}
      </div>`;
  }
  const others = d.contacts.filter((x) => !c || x.id !== c.id);
  const canFind = s.hunter || s.anthropic;
  return `
    <div class="section">
      <h3>Who to contact</h3>
      <div class="small">${esc(co.why)}</div>
      <div class="small muted" style="margin-top:4px">
        ${co.domain ? `Domain: <b>${esc(co.domain)}</b> <span class="muted">(${esc(co.domain_source || "")})</span>`
          : co.suggested_domain ? `Domain: <b>${esc(co.suggested_domain)}</b> <span class="muted">(from the posting)</span>` : "Domain unknown"}
        · <a data-action="edit-domain">${co.domain ? "change" : "set it"}</a>
        ${co.size_range || co.size_count ? ` · Size: <b>${esc(co.size_count || co.size_range)}</b>` : ""}
        ${co.looked_up_at ? ` · looked up ${esc(ago(co.looked_up_at))}${co.credits ? `, ${co.credits} credits` : ""}${co.cost_usd ? `, $${co.cost_usd.toFixed(3)}` : ""}` : ""}
      </div>
      ${co.note ? `<div class="small muted">${esc(co.note)}</div>` : ""}
      ${c ? personCard(c, true) : `<div class="chosen muted">Nobody found yet.</div>`}
      ${d.earlier_at_company.length ? `<div class="warnings">Already emailed at this company: ${d.earlier_at_company.map((e) => `${esc(e.to_addr)} on ${esc(day(e.sent_at))} (“${esc(e.title)}”)`).join("; ")}</div>` : ""}
      ${others.length ? `<details><summary>${others.length} other ${others.length === 1 ? "person" : "people"}</summary>${others.map((x) => personCard(x, false)).join("")}</details>` : ""}
      <div class="row" style="margin-top:10px">
        <button class="btn" data-action="find-contact" ${canFind ? "" : "disabled title='Add HUNTER_API_KEY or ANTHROPIC_API_KEY to .env'"}>${co.looked_up_at ? "Look up again" : "Find contact"}</button>
        ${s.anthropic ? `<button class="btn" data-action="find-contact" data-claude="1" title="Claude searches the web (about $0.03-0.05)">Search the web with Claude</button>` : ""}
        <button class="btn" data-action="show-manual">Add by hand</button>
        <button class="btn small" data-action="job-board" data-value="1" title="Job boards and agencies get no pitch">Not a real employer</button>
      </div>
      <form class="inline" id="manual" hidden>
        <input type="text" name="full_name" placeholder="Name">
        <input type="email" name="email" placeholder="Email">
        <input type="text" name="position" placeholder="Title (e.g. CTO)">
        <button class="btn primary" type="submit">Save</button>
      </form>
    </div>`;
}

function personCard(c, chosen) {
  const canVerify = c.email && ["found", "guessed", "accept_all"].includes(c.email_status) && state.status?.hunter;
  return `
    <div class="${chosen ? "chosen" : "person"}">
      <div class="grow">
        <div><span class="name">${esc(c.full_name)}</span> <span class="chip ${c.is_target ? "info" : ""}">${esc(c.role_label)}</span>
          ${c.position ? `<span class="small muted">${esc(c.position)}</span>` : ""}</div>
        <div class="row small" style="margin-top:3px">
          ${c.email ? `<span class="mono">${esc(c.email)}</span>` : ""} ${emailBadge(c.email ? c.email_status : null)}
          ${c.confidence ? `<span class="muted">${c.confidence}% sure</span>` : ""}
          ${c.linkedin_url ? `<a href="${esc(c.linkedin_url)}" target="_blank" rel="noopener">LinkedIn</a>` : ""}
          <span class="muted">via ${esc(c.source)}${c.verified ? "" : ", not confirmed"}</span>
        </div>
        ${c.evidence_quote || c.evidence_url ? `<div class="quote">${esc(c.evidence_quote || "")} ${c.evidence_url ? `<a href="${esc(c.evidence_url)}" target="_blank" rel="noopener">proof</a>` : ""}</div>` : ""}
      </div>
      <div class="row">
        ${canVerify ? `<button class="btn small" data-action="verify" data-id="${c.id}" title="Hunter Email Verifier, 0.5 credit">Verify</button>` : ""}
        ${chosen ? "" : `<button class="btn small" data-action="use-contact" data-id="${c.id}">Use</button>`}
      </div>
    </div>`;
}

function emailSection(d) {
  const app = d.application || {};
  const out = d.outgoing;
  const s = state.status || {};
  const warnings = app.warnings || [];
  const sentFirst = d.sent.some((m) => m.kind === "first" && m.state === "sent");
  const meta = app.draft_meta;
  const composer = !sentFirst ? `
      <div class="email-to muted">To: ${out ? `<span class="mono">${esc(out.to)}</span>` : esc(d.outgoing_error || "no contact yet")}</div>
      <input type="text" id="subject" value="${esc(app.subject || "")}" placeholder="Subject" style="margin-top:6px">
      <textarea id="body" rows="12" style="margin-top:6px" placeholder="${s.drafts ? "Click “Write with AI”, or write your own." : "Write your email, or add an AI key to .env for drafts."}">${esc(app.body || "")}</textarea>
      <div class="row small muted" style="margin-top:6px">Attaches: ${d.cv.file ? `<b>${esc(d.cv.file)}</b> ${cvLink(d.cv.file)}` : "no CV"} <span>(change it in the CV box)</span></div>
      <div class="row small muted"><span id="wc"></span>${meta ? `<span>· drafted by ${esc(meta.model)}${meta.cost_usd ? `, $${meta.cost_usd.toFixed(3)}` : ""}${app.draft_edited ? ", edited by you" : ""}</span>` : ""}</div>` : "";
  const followUp = sentFirst && out ? `
      <div class="small muted">${out.kind === "follow_up" ? `Follow-up ${out.seq}` : ""} to <span class="mono">${esc(out.to)}</span>
        ${app.next_follow_up_at ? ` · due ${esc(day(app.next_follow_up_at))}` : ""}</div>
      <div class="subject" style="margin-top:6px">${esc(out.subject)}</div>
      <div class="description" style="margin-top:6px">${esc(out.body)}</div>` : sentFirst ? `<div class="muted">${esc(d.outgoing_error || "")}</div>` : "";
  const sendLabel = sentFirst ? (out ? `Send follow-up ${out.seq}` : "") : "Send";
  return `
    <div class="section">
      <h3>${sentFirst ? "Follow-up" : "Email"}</h3>
      ${warnings.length ? `<div class="warnings ${app.draft_blocked ? "block" : ""}">${app.draft_blocked ? "Can't send until you edit it:" : "Check these:"}<ul>${warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>` : ""}
      ${composer}${followUp}
      <div class="row" style="margin-top:10px">
        ${!sentFirst ? `<button class="btn" data-action="draft" ${s.drafts ? "" : "disabled title='Add the AI key to .env'"}>${s.draft_mode === "ai" ? (app.body ? "Rewrite with AI" : "Write with AI") : (app.body ? "Reset to template" : "Fill template")}</button>
          <button class="btn" data-action="save-draft">Save edits</button>
          <button class="btn" data-action="copy">Copy</button>` : ""}
        <span class="grow"></span>
        ${out ? `<button class="btn" data-action="send" data-test="1" ${s.gmail ? "" : "disabled title='Set up Gmail in .env'"}>Send test to me</button>
          <button class="btn primary" data-action="send" ${s.gmail && !(app.draft_blocked && !sentFirst) ? "" : "disabled"}>${esc(sendLabel)}</button>` : ""}
      </div>
      ${!s.gmail ? `<div class="small muted" style="margin-top:6px">Sending needs GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env (an app password from myaccount.google.com/apppasswords).</div>` : ""}
    </div>`;
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
  if (action === "stage") {
    const detail = await busy(el, "…", () => api(`/api/jobs/${id}/stage`, { method: "POST", body: { stage: el.dataset.stage, reason: el.dataset.reason } }));
    return setDetail(detail, `Moved to ${stageLabel(el.dataset.stage, el.dataset.reason)}`);
  }
  if (action === "applied") {
    const detail = await busy(el, "…", () => api(`/api/jobs/${id}/application`, { method: "PATCH", body: { applied: el.dataset.value === "1" } }));
    return setDetail(detail, el.dataset.value === "1" ? "Marked as applied" : "Applied date cleared");
  }
  if (action === "find-contact") {
    const claude = el.dataset.claude === "1";
    const detail = await busy(el, "Looking…", () => api(`/api/jobs/${id}/find-contact`, {
      method: "POST", body: { force: Boolean(d.company.looked_up_at) || claude, use_claude: claude || !state.status.hunter },
    }));
    const l = detail.lookup || {};
    return setDetail(detail, `${l.status === "found" ? "Found" : l.status === "nobody" ? "Nobody found" : l.status}${l.note ? ": " + l.note : ""}`);
  }
  if (action === "show-manual") { $("#manual").hidden = !$("#manual").hidden; return; }
  if (action === "use-contact") {
    const detail = await busy(el, "…", () => api(`/api/jobs/${id}/application`, { method: "PATCH", body: { contact_id: Number(el.dataset.id) } }));
    return setDetail(detail, "Contact changed");
  }
  if (action === "verify") {
    const r = await busy(el, "…", () => api(`/api/contacts/${el.dataset.id}/verify`, { method: "POST" }));
    toast(`Email status: ${r.email_status}`);
    return openJob(id, false);
  }
  if (action === "job-board") {
    const detail = await busy(el, "…", () => api(`/api/jobs/${id}/company`, { method: "POST", body: { is_job_board: el.dataset.value === "1" } }));
    return setDetail(detail);
  }
  if (action === "edit-domain") {
    const value = prompt("Company website domain (e.g. acme.com). Leave empty to clear.", d.company.domain || "");
    if (value === null) return;
    const detail = await api(`/api/jobs/${id}/company`, { method: "POST", body: { domain: value } });
    return setDetail(detail, "Domain saved: click Look up again to use it");
  }
  if (action === "draft") {
    if (d.application?.draft_edited && !confirm("Replace your edited email with a fresh draft?")) return;
    const detail = await busy(el, "Writing…", () => api(`/api/jobs/${id}/draft`, { method: "POST" }));
    return setDetail(detail, detail.application?.draft_blocked ? "Drafted, but it needs an edit" : "Draft ready");
  }
  if (action === "tailor") {
    const detail = await busy(el, "Tailoring… (up to a minute)", () => api(`/api/jobs/${id}/tailor`, { method: "POST" }));
    const t = detail.tailored || {};
    return setDetail(detail, `CV ready: ${t.file}${t.notes?.length ? " (see what code changed)" : ""}`);
  }
  if (action === "cover") {
    if (d.cover && !confirm("Write a new cover letter? It replaces this one, including edits you made to the file.")) return;
    const detail = await busy(el, "Writing… (up to a minute)", () => api(`/api/jobs/${id}/cover`, { method: "POST" }));
    return setDetail(detail, `Cover letter ready: ${detail.cover?.file}${detail.cover?.removed.length ? " (the check left some sentences out)" : ""}`);
  }
  if (action === "copy-cover") {
    await navigator.clipboard.writeText($("#cover-text").value);
    return toast("Copied");
  }
  if (action === "save-draft") return saveDraft(el);
  if (action === "copy") {
    await navigator.clipboard.writeText(`Subject: ${$("#subject").value}\n\n${$("#body").value}`);
    return toast("Copied");
  }
  if (action === "send") return send(el, el.dataset.test === "1");
}

function draftChanged() {
  const app = state.detail?.application || {};
  const subject = $("#subject"), body = $("#body");
  return subject && body && (subject.value !== (app.subject || "") || body.value !== (app.body || ""));
}

async function saveDraft(el) {
  const app = state.detail.application || {};
  const detail = await busy(el, "Saving…", () => api(`/api/jobs/${state.jobId}/application`, {
    method: "PATCH", body: { subject: $("#subject").value, body: $("#body").value, draft_version: app.draft_version ?? null },
  }));
  setDetail(detail, "Saved");
  return detail;
}

async function send(el, test) {
  if (draftChanged()) {
    if (!confirm("Save your edits first? (Send uses the saved version.)")) return;
    await saveDraft(null);
  }
  const d = state.detail;
  const out = d.outgoing;
  if (!out) return toast(d.outgoing_error || "Nothing to send", true);
  const to = test ? state.status.gmail_address : out.to;
  if (!confirm(`${test ? "Send a test copy to yourself" : `Send “${out.subject}”`} to ${to}?`)) return;
  const confirmations = [];
  for (;;) {
    try {
      const detail = await busy(el, "Sending…", () => api(`/api/jobs/${state.jobId}/send`, {
        method: "POST", body: { test, draft_version: state.detail.application.draft_version, seq: out.seq, confirm: confirmations },
      }));
      return setDetail(detail, test ? `Test sent to ${to}` : `Sent to ${to}. Follow-up reminder set.`);
    } catch (err) {
      if (err.status === 409 && err.confirm && !confirmations.includes(err.confirm) && confirm(err.message)) {
        confirmations.push(err.confirm);
        continue;
      }
      return;
    }
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
      ${card("New shortlisted to triage", t.new_jobs.map((r) => item(r, ` <span class="chip">fit ${r.fit_score}</span>
        <span class="row" style="margin-top:4px"><button class="btn small" data-quick="saved" data-id="${r.id}">Save</button><button class="btn small danger" data-quick="skipped" data-id="${r.id}">Skip</button></span>`)), "All caught up.")}
      ${t.unsure_sends.length ? card("Sends to double-check", t.unsure_sends.map((r) => item(r, `<div class="small muted">Gmail didn't confirm ${esc(r.subject)}: Check inbox resolves it.</div>`)), "") : ""}
      ${card("Ghosted this week", t.ghosted.map((r) => item(r, `<div class="small muted">closed ${esc(day(r.at))}</div>`)), "None.")}
      <div class="card"><h2>Today</h2><div class="big">${t.sends_today.total}<span class="muted small"> / ${t.caps.total} emails sent</span></div>
        <div class="muted small">Guessed addresses: ${t.sends_today.guessed} / ${t.caps.guessed}. Best reply rates: Tue–Thu mornings in their time zone.</div></div>
    </div>`;
}

// --- pipeline ----------------------------------------------------------------------

async function renderPipeline() {
  const [tracked, closed] = await Promise.all([api("/api/jobs?view=tracked"), api("/api/jobs?view=closed")]);
  const jobs = [...tracked.jobs, ...closed.jobs];
  const stages = (state.status?.stages || []).filter((s) => s !== "new");
  $("#main").innerHTML = `<div class="board">${stages.map((stage) => {
    const cards = jobs.filter((j) => j.stage === stage);
    return `<div class="column"><h3>${esc(stageLabel(stage))} <span>${cards.length}</span></h3>${cards.map((j) => `
      <div class="pcard">
        <div class="job-title" data-open="${j.id}">${esc(j.title)}</div>
        <div class="small muted">${esc(j.company)}</div>
        <div class="job-meta small" style="margin-top:4px">
          ${j.applied_at ? `<span class="chip">applied</span>` : ""}${j.emailed_at ? `<span class="chip info">emailed ${esc(day(j.emailed_at))}</span>` : ""}
          ${j.stage === "reached_out" && j.next_follow_up_at ? `<span class="chip ${new Date(j.next_follow_up_at) <= new Date() ? "warn" : ""}">follow-up ${esc(day(j.next_follow_up_at))}</span>` : ""}
          ${j.closed_reason ? `<span class="chip">${esc(j.closed_reason)}</span>` : ""}
        </div>
        <select data-move="${j.id}">${stages.map((s) => `<option value="${s}" ${s === stage ? "selected" : ""}>${esc(stageLabel(s))}</option>`).join("")}</select>
      </div>`).join("") || `<div class="small muted" style="margin-top:8px">Empty</div>`}</div>`;
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
    if (quick) {
      e.stopPropagation();
      const reason = quick.dataset.quick === "skipped" ? "skipped" : undefined;
      await busy(quick, "…", () => api(`/api/jobs/${quick.dataset.id}/stage`, {
        method: "POST", body: { stage: reason ? "closed" : "saved", reason },
      }));
      toast(reason ? "Skipped" : "Saved");
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
    if (e.target.matches("[data-move]")) {
      const stage = e.target.value;
      const reason = stage === "closed" ? prompt("Why closed? rejected, ghosted or skipped", "rejected") : undefined;
      if (stage === "closed" && !reason) return renderPipeline();
      await api(`/api/jobs/${e.target.dataset.move}/stage`, { method: "POST", body: { stage, reason } });
      toast(`Moved to ${stageLabel(stage, reason)}`);
      return renderPipeline();
    }
  } catch (err) {
    toast(err.message, true);
  }
});

document.addEventListener("focusout", async (e) => {
  if (e.target.id !== "notes" || !state.detail) return;
  const notes = e.target.value;
  if (notes === (state.detail.application?.notes || "")) return;
  try {
    state.detail = await api(`/api/jobs/${state.jobId}/application`, { method: "PATCH", body: { notes } });
    toast("Notes saved");
  } catch (err) { toast(err.message, true); }
});

document.addEventListener("input", (e) => {
  if (e.target.id === "body" || e.target.id === "subject") updateWordCount();
});

document.addEventListener("submit", async (e) => {
  if (e.target.id !== "manual") return;
  e.preventDefault();
  const form = new FormData(e.target);
  try {
    const detail = await api(`/api/jobs/${state.jobId}/contact`, { method: "PUT", body: Object.fromEntries(form) });
    setDetail(detail, "Contact saved");
  } catch (err) { toast(err.message, true); }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && state.jobId) closeDrawer();
});
$("#scrim").addEventListener("click", () => closeDrawer());

function updateWordCount() {
  const body = $("#body");
  if (!body || !$("#wc")) return;
  const words = (body.value.match(/[A-Za-z0-9]+/g) || []).length;
  $("#wc").textContent = `${words} words${words > 125 ? " (long: 50–125 gets the most replies)" : ""}`;
}
const observer = new MutationObserver(updateWordCount);
observer.observe($("#drawer-body"), { childList: true });

window.addEventListener("hashchange", route);
loadStatus().then(route).catch((err) => { $("#main").innerHTML = `<div class="empty">${esc(err.message)}</div>`; });
