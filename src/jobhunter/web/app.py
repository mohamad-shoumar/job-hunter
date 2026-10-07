"""The local web app behind `jobhunter serve`: a JSON API over the same SQLite DB, and one page.

Locked to you:
  - it listens on 127.0.0.1 only;
  - requests whose Host is not 127.0.0.1/localhost on this port are refused,
    which stops DNS-rebinding pages from reaching it;
  - every request that changes something needs the random token put into the
    page at startup (X-JH-Token), a JSON body and no foreign Origin, so another
    website open in your browser cannot press Send for you. There is no CORS,
    except on GET /api/cv/...: any page may read a CV PDF (Chrome asks you once
    per site before a site reaches this computer), so a job site can attach it
    when the Chrome extension applies for you. Nothing there changes anything.

Each request opens its own SQLite connection; the schema is migrated once at
startup. Emails are sent only by POST /api/jobs/{id}/send, i.e. by your click.
"""

from __future__ import annotations

import hmac
import json
import os
import sqlite3
from pathlib import Path
from typing import Callable

from fastapi import Body, Depends, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .. import tracking
from ..config import OutreachConfig, Paths
from ..cover import CoverError, build_cover_writer, cover_for_job, cover_model, cover_of, letter_text
from ..cv import (
    TailorError, build_cv_writer, build_pdf, check_version, save_version, tailor_for_job, tailor_note, tailored_of,
    version_of,
)
from ..contacts import (
    ROLE_LABELS, ContactFinder, chosen_contact, clean_company_name, company_contacts, domain_from_links, job_company,
    rank_contacts, save_manual_contact, set_domain, set_job_board, skip_list_match, targets_for, verify_email,
)
from ..hunter import Hunter, HunterError
from ..llm import CLAUDE_CODE, anthropic_client, error_line, key_note
from ..mailer import GmailInbox, MailAccount, SendError, SmtpSender, check_inbox, mail_account, outgoing, send_for_job
from ..pitch import PitchWriter, build_writer, cv_for, cv_options, draft_for_job, edit_draft, load_profile, reassemble, word_count
from ..report import _salary
from ..store import JobStore
from ..text import parse_datetime, utcnow

STATIC = Path(__file__).parent / "static"
_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
# Only CV PDFs are open to other sites (see the top of this file).
_CV_CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Private-Network": "true"}


class Services:
    """What the endpoints use to reach the outside world. Tests swap these for fakes.

    The Hunter and Claude clients are made once and shared; a ContactFinder
    (which remembers "Hunter is out of credits" for one run) is new per request.
    """

    def __init__(self, config: OutreachConfig):
        self.config = config
        self._hunter: Hunter | None = None
        self._claude = None

    def _clients(self):
        if self._hunter is None and os.environ.get("HUNTER_API_KEY"):
            self._hunter = Hunter(os.environ["HUNTER_API_KEY"])
        if self._claude is None:
            self._claude = anthropic_client()
        return self._hunter, self._claude

    def finder(self) -> tuple[ContactFinder | None, str | None]:
        hunter, claude = self._clients()
        if hunter is None and claude is None:
            return None, "Contact lookup needs HUNTER_API_KEY (and/or ANTHROPIC_API_KEY) in .env"
        return ContactFinder(self.config, hunter, claude), None

    def writer(self) -> tuple[PitchWriter | None, str | None]:
        if self.config.pitch_model.startswith("deepseek"):
            return build_writer(self.config)
        _, claude = self._clients()
        return build_writer(self.config, claude=claude)

    def cv_writer(self):
        claude = None if self.config.cv_model.startswith("deepseek") else self._clients()[1]
        return build_cv_writer(self.config, claude=claude)

    def cover_writer(self):
        claude = None if cover_model(self.config).startswith(("deepseek", CLAUDE_CODE)) else self._clients()[1]
        return build_cover_writer(self.config, claude=claude)

    def build_pdf(self, folder: Path, source: Path) -> tuple[Path, int]:
        return build_pdf(folder, source)

    def account(self) -> MailAccount | None:
        return mail_account()

    def sender(self, account: MailAccount):
        return SmtpSender(account)

    def inbox(self, account: MailAccount) -> GmailInbox:
        return GmailInbox(account)


def create_app(paths: Paths, token: str, allowed_hosts: list[str] | None = None,
               services: Services | None = None, now: Callable = utcnow) -> FastAPI:
    config = OutreachConfig.load(paths.outreach_file)
    services = services or Services(config)
    allowed_origins = {f"http://{h}" for h in allowed_hosts or []}
    JobStore(paths.db_file).close()  # migrate once
    app = FastAPI(title="jobhunter", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = request.headers.get("host", "")
        if allowed_hosts is not None and host not in allowed_hosts:
            return JSONResponse({"error": "wrong host"}, status_code=403)
        if request.url.path.startswith("/api/cv/"):
            if request.method == "OPTIONS":  # the browser asks first: allow reading, nothing else
                return Response(status_code=204, headers={**_CV_CORS, "Access-Control-Allow-Methods": "GET"})
            if request.method not in ("GET", "HEAD"):
                return JSONResponse({"error": "CVs can only be read"}, status_code=405)
            response = await call_next(request)
            response.headers.update(_CV_CORS)
            return response
        if request.method in _MUTATING:
            origin = request.headers.get("origin")
            if origin and allowed_hosts is not None and origin not in allowed_origins:
                return JSONResponse({"error": "wrong origin"}, status_code=403)
            if not hmac.compare_digest(request.headers.get("x-jh-token", ""), token):
                return JSONResponse({"error": "missing or wrong token: reload the page"}, status_code=403)
            if not request.headers.get("content-type", "").startswith("application/json"):
                return JSONResponse({"error": "send JSON"}, status_code=415)
        return await call_next(request)

    @app.exception_handler(SendError)
    async def send_error(request: Request, exc: SendError):
        return JSONResponse({"error": str(exc), "confirm": exc.confirm}, status_code=409)

    @app.exception_handler(tracking.TrackingError)
    async def tracking_error(request: Request, exc: tracking.TrackingError):
        return JSONResponse({"error": str(exc)}, status_code=400)

    @app.exception_handler(HunterError)
    async def hunter_error(request: Request, exc: HunterError):
        return JSONResponse({"error": str(exc)}, status_code=502)

    def db():
        store = JobStore(paths.db_file, migrate=False, check_same_thread=False)
        try:
            yield store
        finally:
            store.close()

    def profile():
        return load_profile(paths.profile_file)

    def job_or_404(store: JobStore, job_id: int) -> sqlite3.Row:
        row = store.get(job_id)
        if row is None:
            raise tracking.TrackingError(f"no job #{job_id}")
        return row

    # --- the page ------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    def index():
        html = (STATIC / "index.html").read_text().replace("__JH_TOKEN__", token)
        # The browser keeps app.js and style.css for a while without asking (no cache header), so after an
        # update it would run the old code. A version in the link makes a changed file a new URL.
        for name in ("app.js", "style.css"):
            html = html.replace(f"/static/{name}\"", f"/static/{name}?v={int((STATIC / name).stat().st_mtime)}\"")
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/favicon.ico")
    def favicon():
        return FileResponse(STATIC / "favicon.svg", media_type="image/svg+xml")

    # --- reading ---------------------------------------------------------------

    @app.get("/api/status")
    def status(credits: bool = False, store: JobStore = Depends(db)):
        finder, _ = services.finder() if credits else (None, None)
        account = finder.account() if finder else None
        return {
            "hunter": bool(os.environ.get("HUNTER_API_KEY")),
            "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "drafts": config.pitch_mode != "ai" or services.writer()[0] is not None,
            "draft_model": "your template" if config.pitch_mode != "ai" else config.pitch_model,
            "draft_mode": config.pitch_mode,
            "gmail": services.account() is not None,
            "gmail_address": (services.account() or MailAccount("", "")).address,
            "hunter_credits": account.__dict__ if account else None,
            "caps": {"total": config.daily_send_cap, "guessed": config.daily_guessed_cap},
            "cv_model": config.cv_model, "cv_tailor_note": tailor_note(config),
            "cover_model": cover_model(config), "cover_note": key_note(cover_model(config), "Cover letters"),
            "sends_today": tracking.sends_today(store, now()),
            "stages": tracking.STAGES, "stage_labels": tracking.STAGE_LABELS,
            "closed_reasons": tracking.CLOSED_REASONS, "role_labels": ROLE_LABELS,
        }

    @app.get("/api/jobs")
    def jobs(view: str = "active", q: str = "", store: JobStore = Depends(db)):
        where = {
            "active": "j.status IN ('shortlisted', 'needs_review') AND COALESCE(a.stage, 'new') != 'closed'",
            "shortlisted": "j.status = 'shortlisted' AND COALESCE(a.stage, 'new') != 'closed'",
            "needs_review": "j.status = 'needs_review' AND COALESCE(a.stage, 'new') != 'closed'",
            "tracked": "a.stage IS NOT NULL AND a.stage NOT IN ('new', 'closed')",
            "closed": "a.stage = 'closed'",
            "rejected": "j.status = 'rejected' AND j.report_date IS NOT NULL",
        }.get(view)
        if where is None:
            raise tracking.TrackingError(f"unknown view {view!r}")
        params: list = []
        if q.strip():
            where += " AND (j.title LIKE ? OR j.company LIKE ?)"
            params += [f"%{q.strip()}%"] * 2
        rows = store.conn.execute(
            f"""
            SELECT j.*, a.stage, a.closed_reason, a.body IS NOT NULL AS has_draft, a.draft_blocked,
                   a.next_follow_up_at, a.emailed_at, a.applied_at, a.replied_at,
                   a.cv_tailored_json IS NOT NULL AS has_cv, a.cover_letter_json IS NOT NULL AS has_cover
            FROM jobs j LEFT JOIN applications a ON a.job_id = j.id
            WHERE {where}
            ORDER BY COALESCE(j.report_date, substr(j.first_seen, 1, 10)) DESC,
                     CASE j.status WHEN 'shortlisted' THEN 0 ELSE 1 END, j.fit_score DESC, j.id DESC
            LIMIT 500
            """,
            params,
        ).fetchall()
        return {"jobs": [_job_summary(store, row, config) for row in rows]}

    @app.get("/api/jobs/{job_id}")
    def job(job_id: int, store: JobStore = Depends(db)):
        row = job_or_404(store, job_id)
        return _job_detail(store, row, config, services, profile(), now())

    @app.get("/api/today")
    def today(store: JobStore = Depends(db)):
        return tracking.today(store, now(), config)

    @app.get("/api/stats")
    def stats(store: JobStore = Depends(db)):
        data = tracking.stats(store, now(), config)
        data["role_labels"] = ROLE_LABELS
        return data

    # --- changing --------------------------------------------------------------

    @app.post("/api/jobs/{job_id}/stage")
    def stage(job_id: int, body: dict | None = Body(default=None), store: JobStore = Depends(db)):
        body = body or {}
        job_or_404(store, job_id)
        tracking.set_stage(store, job_id, body.get("stage"), now(), reason=body.get("reason"))
        store.commit()
        return _job_detail(store, store.get(job_id), config, services, profile(), now())

    @app.patch("/api/jobs/{job_id}/application")
    def application(job_id: int, body: dict | None = Body(default=None), store: JobStore = Depends(db)):
        body = body or {}
        job_or_404(store, job_id)
        t = now()
        me = profile()
        tracking.ensure_application(store, job_id, t)
        if "notes" in body:
            tracking.update_notes(store, job_id, str(body["notes"] or ""), t)
        if "applied" in body:
            when = parse_datetime(body.get("applied_at")) if body.get("applied_at") else t
            tracking.mark_applied(store, job_id, when if body["applied"] else None, t)
            reassemble(store, job_id, me, t, config)
        if "contact_id" in body:
            contact_id = int(body["contact_id"])
            company = job_company(store, store.get(job_id), t)
            if not store.conn.execute("SELECT 1 FROM contacts WHERE id = ? AND company_key = ?",
                                      (contact_id, company["key"])).fetchone():
                raise tracking.TrackingError("that contact is not at this company")
            store.conn.execute("UPDATE applications SET contact_id = ? WHERE job_id = ?", (contact_id, job_id))
            reassemble(store, job_id, me, t, config)
        if "cv_file" in body:
            choice = str(body["cv_file"] or "")
            if choice not in ("", "none", *cv_options(config)):
                raise tracking.TrackingError(f"no CV named {choice} in {config.cv_dir}")
            store.conn.execute("UPDATE applications SET cv_file = ? WHERE job_id = ?", (choice or None, job_id))
            reassemble(store, job_id, me, t, config)
        if "subject" in body or "body" in body:
            app_row = tracking.get_application(store, job_id)
            if body.get("draft_version") is not None and int(body["draft_version"]) != app_row["draft_version"]:
                raise tracking.TrackingError("The draft changed since this page loaded (the daily run or another "
                                             "tab). Reload before editing.")
            edit_draft(store, job_id, str(body.get("subject", app_row["subject"] or "")),
                       str(body.get("body", app_row["body"] or "")), me, t)
        store.commit()
        return _job_detail(store, store.get(job_id), config, services, me, t)

    @app.put("/api/jobs/{job_id}/contact")
    def manual_contact(job_id: int, body: dict | None = Body(default=None), store: JobStore = Depends(db)):
        body = body or {}
        job_or_404(store, job_id)
        t = now()
        if not (body.get("full_name") or "").strip() and not (body.get("email") or "").strip():
            raise tracking.TrackingError("give a name or an email")
        save_manual_contact(store, job_id, str(body.get("full_name") or ""), str(body.get("email") or ""),
                            str(body.get("position") or ""), t)
        reassemble(store, job_id, profile(), t, config)
        store.commit()
        return _job_detail(store, store.get(job_id), config, services, profile(), t)

    @app.post("/api/jobs/{job_id}/company")
    def company(job_id: int, body: dict | None = Body(default=None), store: JobStore = Depends(db)):
        body = body or {}
        row = job_or_404(store, job_id)
        company_row = job_company(store, row, now())
        if "is_job_board" in body:
            set_job_board(store, company_row["key"], bool(body["is_job_board"]))
        if "domain" in body:
            set_domain(store, company_row["key"], str(body["domain"] or ""))
            store.conn.execute("UPDATE companies SET lookup_state = NULL WHERE key = ?", (company_row["key"],))
        store.commit()
        return _job_detail(store, store.get(job_id), config, services, profile(), now())

    @app.post("/api/jobs/{job_id}/find-contact")
    def find_contact(job_id: int, body: dict | None = Body(default=None), store: JobStore = Depends(db)):
        body = body or {}
        row = job_or_404(store, job_id)
        finder, note = services.finder()
        if finder is None:
            raise tracking.TrackingError(note or "no lookup service configured")
        result = finder.lookup(store, row, now(), use_claude=bool(body.get("use_claude", True)),
                               force=bool(body.get("force")))
        store.commit()
        detail = _job_detail(store, store.get(job_id), config, services, profile(), now())
        detail["lookup"] = result.__dict__
        return detail

    @app.post("/api/contacts/{contact_id}/verify")
    def verify(contact_id: int, body: dict | None = Body(default=None), store: JobStore = Depends(db)):
        finder, note = services.finder()
        if finder is None or finder.hunter is None:
            raise tracking.TrackingError("verifying needs HUNTER_API_KEY")
        status = verify_email(store, finder.hunter, contact_id)
        store.commit()
        return {"email_status": status}

    @app.post("/api/jobs/{job_id}/draft")
    def draft(job_id: int, body: dict | None = Body(default=None), store: JobStore = Depends(db)):
        job_or_404(store, job_id)
        writer, note = (None, None) if config.pitch_mode != "ai" else services.writer()
        if config.pitch_mode == "ai" and writer is None:
            raise tracking.TrackingError(note or "drafting is off")
        draft_for_job(store, job_id, writer, profile(), config, now(), force=True)
        store.commit()
        return _job_detail(store, store.get(job_id), config, services, profile(), now())

    @app.post("/api/jobs/{job_id}/tailor")
    def tailor(job_id: int, body: dict | None = Body(default=None), store: JobStore = Depends(db)):
        job_or_404(store, job_id)
        writer, note = services.cv_writer()
        if writer is None:
            raise tracking.TrackingError(note or "tailoring is off")
        try:
            result = tailor_for_job(store, job_id, writer, paths.profile_file, config, now(), builder=services.build_pdf,
                                    replace_edits=bool((body or {}).get("replace_edits")))
        except TailorError:
            raise
        except Exception as exc:  # the model or build.py failed: say so on the page
            raise TailorError(f"Tailoring failed: {error_line(exc)}") from exc
        detail = _job_detail(store, store.get(job_id), config, services, profile(), now())
        detail["tailored"] = result
        return detail

    @app.get("/api/jobs/{job_id}/cv-text")
    def cv_text(job_id: int, store: JobStore = Depends(db)):
        """The text behind the job's CV (versions/<name>.md), to edit, and the lines that say more than the profile."""
        row = job_or_404(store, job_id)
        company, _ = clean_company_name(row["company"])
        source = version_of(config, company, tracking.get_application(store, job_id))
        if source is None:
            return JSONResponse({"error": "This job uses the general CV: tailor one first"}, status_code=404)
        text = source.read_text()
        folder = Path(config.resume_dir).expanduser().resolve()
        return {"source": str(source.relative_to(folder)), "text": text,
                "checks": check_version(text, paths.profile_file)}

    @app.put("/api/jobs/{job_id}/cv-text")
    def save_cv_text(job_id: int, body: dict | None = Body(default=None), store: JobStore = Depends(db)):
        """Save your edit and rebuild the PDF with build.py. No model: what you save is what prints."""
        job_or_404(store, job_id)
        text = (body or {}).get("text")
        if not isinstance(text, str):
            raise TailorError("send the CV text as {\"text\": ...}")
        try:
            result = save_version(store, job_id, config, paths.profile_file, now(), text, builder=services.build_pdf)
        except TailorError:
            raise
        except Exception as exc:  # build.py failed: say so on the page
            raise TailorError(f"Rebuilding the PDF failed: {error_line(exc)}") from exc
        detail = _job_detail(store, store.get(job_id), config, services, profile(), now())
        detail["cv_saved"] = result
        return detail

    @app.post("/api/jobs/{job_id}/cover")
    def cover(job_id: int, body: dict | None = Body(default=None), store: JobStore = Depends(db)):
        job_or_404(store, job_id)
        writer, note = services.cover_writer()
        if writer is None:
            raise tracking.TrackingError(note or "cover letters are off")
        try:
            cover_for_job(store, job_id, writer, paths.profile_file, config, now())
        except CoverError:
            raise
        except Exception as exc:  # the model failed, or the folder cannot be written: say so on the page
            raise CoverError(f"Writing the cover letter failed: {error_line(exc)}") from exc
        return _job_detail(store, store.get(job_id), config, services, profile(), now())

    @app.get("/api/cv/{name}")
    def cv_pdf(name: str, download: bool = False):
        """A CV from cv_dir, shown in the browser (or saved, with ?download=1). Only names listed there, so no
        other file can be read."""
        if name not in cv_options(config):
            return JSONResponse({"error": f"no CV named {name} in {config.cv_dir}"}, status_code=404)
        return FileResponse(Path(config.cv_dir).expanduser() / name, media_type="application/pdf", filename=name,
                            content_disposition_type="attachment" if download else "inline",
                            headers={"Cache-Control": "no-store"})

    @app.post("/api/jobs/{job_id}/send")
    def send(job_id: int, body: dict | None = Body(default=None), store: JobStore = Depends(db)):
        body = body or {}
        job_or_404(store, job_id)
        account = services.account()
        if account is None:
            raise tracking.TrackingError("Gmail is not set up: add GMAIL_ADDRESS and GMAIL_APP_PASSWORD to .env")
        me = profile()
        account = MailAccount(account.address, account.password, me.name)
        result = send_for_job(store, job_id, services.sender(account), account, me, config, now(),
                              draft_version=int(body.get("draft_version", -1)), test=bool(body.get("test")),
                              confirm=set(body.get("confirm") or []),
                              seq=int(body["seq"]) if body.get("seq") is not None else None)
        detail = _job_detail(store, store.get(job_id), config, services, me, now())
        detail["sent"] = result
        return detail

    @app.post("/api/inbox/check")
    def inbox_check(body: dict | None = Body(default=None), store: JobStore = Depends(db)):
        account = services.account()
        if account is None:
            raise tracking.TrackingError("Gmail is not set up: add GMAIL_ADDRESS and GMAIL_APP_PASSWORD to .env")
        has_mail = store.conn.execute("SELECT 1 FROM sent_mail WHERE state != 'failed' LIMIT 1").fetchone()
        inbox = services.inbox(account) if has_mail else None
        try:
            result = check_inbox(store, account, config, now(), inbox=inbox)
        finally:
            if inbox is not None:
                inbox.close()
        return result.to_dict()

    return app


# --- JSON shapes ----------------------------------------------------------------------


def _reasons(row: sqlite3.Row, column: str) -> list[str]:
    return json.loads(row[column] or "[]")


def _contact_json(contact: sqlite3.Row | None, targets: list[str] | None = None) -> dict | None:
    if contact is None:
        return None
    data = dict(contact)
    data["role_label"] = ROLE_LABELS.get(contact["role"], contact["role"])
    if targets is not None:
        data["is_target"] = contact["role"] in targets
    return data


def _job_summary(store: JobStore, row: sqlite3.Row, config: OutreachConfig) -> dict:
    contact = chosen_contact(store, row, config)
    reasons = _reasons(row, "eligibility_reasons_json")
    company, _ = clean_company_name(row["company"])
    return {
        "id": row["id"], "title": row["title"], "company": company, "status": row["status"],
        "eligibility": row["eligibility"], "reason": reasons[0] if reasons else "", "fit": row["fit_score"],
        "salary": _salary(row), "posted_at": row["posted_at"], "first_seen": row["first_seen"],
        "report_date": row["report_date"], "source": row["source"],
        "apply_url": row["application_url"] or row["source_url"],
        "stage": row["stage"] or "new", "closed_reason": row["closed_reason"], "has_draft": bool(row["has_draft"]),
        "draft_blocked": bool(row["draft_blocked"]), "emailed_at": row["emailed_at"], "applied_at": row["applied_at"],
        "has_cv": bool(row["has_cv"]), "has_cover": bool(row["has_cover"]),
        "replied_at": row["replied_at"], "next_follow_up_at": row["next_follow_up_at"],
        "job_board": skip_list_match(row["company"], config),
        "contact": {"name": contact["full_name"], "role": ROLE_LABELS.get(contact["role"], contact["role"]),
                    "email_status": contact["email_status"] if contact["email"] else None} if contact else None,
    }


def _cover_json(config: OutreachConfig, app) -> dict | None:
    """The job's cover letter as it is on disk now (you may have edited the file), and what the check did."""
    meta = cover_of(app)
    if not meta:
        return None
    return {**{k: v for k, v in meta.items() if k != "text"}, "text": letter_text(config, meta)}


def _job_detail(store: JobStore, row: sqlite3.Row, config: OutreachConfig, services: Services, profile, now) -> dict:
    company = job_company(store, row, now)
    store.commit()
    targets, why = targets_for(company["size_range"], company["size_count"], config)
    contacts = rank_contacts(company_contacts(store, company["key"]), targets)
    chosen = chosen_contact(store, row, config)
    app = tracking.get_application(store, row["id"])
    sent = store.conn.execute("SELECT * FROM sent_mail WHERE job_id = ? ORDER BY id", (row["id"],)).fetchall()
    preview, preview_error = None, None
    account = services.account()
    if app and app["body"]:
        try:
            out = outgoing(store, row["id"], False, account or MailAccount("you@gmail.com", ""), profile, config)
            preview = {"kind": out.kind, "seq": out.seq, "to": out.to, "subject": out.subject, "body": out.body,
                       "guessed": out.guessed, "words": word_count(out.body)}
        except SendError as exc:
            preview_error = str(exc)
    earlier = tracking.company_contacted(store, company["key"], row["id"])
    sightings = store.sightings_for([row["id"]])[row["id"]]
    return {
        "job": {
            "id": row["id"], "title": row["title"], "company": company["name"], "status": row["status"],
            "eligibility": row["eligibility"], "eligibility_reasons": _reasons(row, "eligibility_reasons_json"),
            "relevance": row["relevance"], "relevance_reasons": _reasons(row, "relevance_reasons_json"),
            "fit": row["fit_score"], "skills": _reasons(row, "skills_json"), "salary": _salary(row),
            "remote_status": row["remote_status"], "location": row["location_raw"],
            "employment_type": row["employment_type"], "required_yoe": row["required_yoe"],
            "posted_at": row["posted_at"], "first_seen": row["first_seen"], "report_date": row["report_date"],
            "apply_url": row["application_url"] or row["source_url"], "description": row["description"],
            "reject_reason": row["reject_reason"],
            "ai_check": json.loads(row["ai_check_json"]) if row["ai_check_json"] else None,
            "seen_on": [{"source": s["source"], "url": s["source_url"]} for s in sightings],
        },
        "company": {**dict(company), "targets": [ROLE_LABELS[t] for t in targets], "why": why,
                    "skip_listed": skip_list_match(row["company"], config),
                    "suggested_domain": None if company["domain"] else domain_from_links(
                        row["company"], [row["application_url"] or "", row["source_url"] or "", row["description"] or ""])},
        "contacts": [_contact_json(c, targets) for c in contacts],
        "contact": _contact_json(chosen, targets),
        "application": {**dict(app), "warnings": tracking.warnings_of(app),
                        "draft_meta": json.loads(app["draft_meta_json"]) if app["draft_meta_json"] else None}
        if app else None,
        "events": [dict(e) for e in tracking.events_for(store, row["id"])],
        "sent": [dict(s) for s in sent],
        "outgoing": preview, "outgoing_error": preview_error,
        "earlier_at_company": [dict(e) for e in earlier],
        "cv": {"options": cv_options(config), "chosen": app["cv_file"] if app else None,
               "file": (lambda f: f.name if f else None)(cv_for(config, company["name"], app["cv_file"] if app else None)),
               "folder": config.cv_dir, "tailored": tailored_of(app),
               "source": (lambda s: s.name if s else None)(version_of(config, company["name"], app))},
        "cover": _cover_json(config, app),
        "sends_today": tracking.sends_today(store, now),
        "caps": {"total": config.daily_send_cap, "guessed": config.daily_guessed_cap},
    }
