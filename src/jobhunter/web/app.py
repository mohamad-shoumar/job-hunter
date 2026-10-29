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
startup. A GET never writes, so it holds no write lock while the daily run
writes. Emails are sent only by POST /api/jobs/{id}/send, i.e. by your click.

Every error is {"error": "..."} (plus "confirm" from Send), with the status
its kind carries (errors.py): 400 for a request that makes no sense, or a
value of the wrong type (the request bodies below name the field), 404 for
no such job, 409 when the job changed since the page loaded, 502 when the
model, build.py, Hunter or Gmail failed.
"""

from __future__ import annotations

import hmac
import json
import os
import sqlite3
from datetime import datetime, time, timedelta
from pathlib import Path
from collections.abc import Callable

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from .. import tracking
from ..config import OutreachConfig, Paths
from ..cover import build_cover_writer, cover_for_job, cover_model, cover_of, letter_text
from ..cv import (
    build_cv_writer, build_pdf, check_version, save_version, tailor_for_job, tailor_note, tailored_of, version_of,
)
from ..contacts import (
    ROLE_LABELS, ContactFinder, chosen_contact, chosen_contacts, clean_company_name, company_ref, domain_from_links,
    ensure_company, job_company, rank_contacts, save_manual_contact, set_domain, set_job_board, skip_list_match,
    targets_for, verify_email,
)
from ..errors import AppError, BadRequest, Conflict, NotFound, UpstreamError
from ..fitgrade import grade_of
from ..hunter import Hunter
from ..llm import anthropic_client, error_line, key_note
from ..mailer import GmailInbox, MailAccount, SendError, SmtpSender, check_inbox, mail_account, outgoing, send_for_job
from ..models import NEW, SAVED, STAGE_LABELS, STAGES
from ..pipeline import local_day
from ..pitch import PitchWriter, build_writer, cv_for, cv_options, draft_for_job, edit_draft, reassemble, word_count
from ..profile import load_profile
from ..report import salary_text
from ..store import JobStore
from ..store.applications import events_for, get_application, set_application_contact, set_cv_file
from ..store.companies import company_contacts, contact_at, forget_lookup
from ..store.lists import JOB_VIEWS, YEARS, job_list
from ..store.mail import company_contacted, has_mail, mail_for_job
from ..text import parse_datetime, utcnow

STATIC = Path(__file__).parent / "static"
_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
# Only CV PDFs are open to other sites (see the top of this file).
_CV_CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Private-Network": "true"}


# --- request bodies: FastAPI checks each value's type, and a wrong one is a 400 naming the field ---------


class _Body(BaseModel):
    model_config = ConfigDict(extra="ignore")  # keys a route does not use are left alone


class StageChange(_Body):
    stage: str
    reason: str | None = None  # closed: rejected, ghosted or skipped
    skip_reason: str | None = None
    skip_note: str | None = None


class ApplicationChange(_Body):
    """Only the keys sent are changed (model_fields_set)."""
    notes: str | None = None
    applied: bool | None = None
    applied_at: str | None = None  # with applied: when (default now)
    contact_id: int | None = None
    cv_file: str | None = None
    subject: str | None = None
    body: str | None = None
    draft_version: int | None = None  # the version the page showed, so an edit never overwrites a newer draft


class ManualContact(_Body):
    full_name: str | None = None
    email: str | None = None
    position: str | None = None


class CompanyChange(_Body):
    """Only the keys sent are changed (model_fields_set)."""
    is_job_board: bool | None = None
    domain: str | None = None


class ContactLookup(_Body):
    use_claude: bool = True
    force: bool = False


class TailorRequest(_Body):
    replace_edits: bool = False


class CvText(_Body):
    text: str


class SendRequest(_Body):
    draft_version: int = -1  # the version the page showed, and the step (seq): a double click sends nothing
    seq: int | None = None
    test: bool = False
    confirm: list[str] | None = None  # what you said yes to: guessed, same_company, early


def _validation_message(exc: RequestValidationError) -> str:
    """'contact_id: Input should be a valid integer...': the first problem, by field."""
    error = exc.errors()[0]
    if error.get("type") == "json_invalid":
        return "The request body is not valid JSON"
    field = ".".join(str(part) for part in error.get("loc", ())[1:]) or "body"
    return f"{field}: {error.get('msg', 'not valid')}"


class Services:
    """What the endpoints use to reach the outside world. Tests swap these for fakes.

    The Hunter and Claude clients are made once and shared; a ContactFinder
    (which remembers "Hunter is out of credits" for one run) is new per request.
    The writers get the shared Claude client and use it only when their model is
    a Claude one (llm.json_model decides).
    """

    def __init__(self, config: OutreachConfig):
        self.config = config
        self._hunter: Hunter | None = None
        self._claude = None

    def _clients(self):
        if self._hunter is None and os.environ.get("HUNTER_API_KEY"):
            self._hunter = Hunter(os.environ["HUNTER_API_KEY"])
        return self._hunter, self._claude_client()

    def _claude_client(self):
        if self._claude is None:
            self._claude = anthropic_client()
        return self._claude

    def finder(self) -> tuple[ContactFinder | None, str | None]:
        hunter, claude = self._clients()
        if hunter is None and claude is None:
            return None, "Contact lookup needs HUNTER_API_KEY (and/or ANTHROPIC_API_KEY) in .env"
        return ContactFinder(self.config, hunter, claude), None

    def writer(self) -> tuple[PitchWriter | None, str | None]:
        return build_writer(self.config, claude=self._claude_client())

    def cv_writer(self):
        return build_cv_writer(self.config, claude=self._claude_client())

    def cover_writer(self):
        return build_cover_writer(self.config, claude=self._claude_client())

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

    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError):
        return JSONResponse(exc.to_dict(), status_code=exc.http_status)

    @app.exception_handler(RequestValidationError)
    async def bad_value(request: Request, exc: RequestValidationError):
        # FastAPI's own answer is a 422 listing every problem as objects; the page shows one line.
        return JSONResponse({"error": _validation_message(exc)}, status_code=400)

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
            raise NotFound(f"no job #{job_id}")
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
            "stages": STAGES, "stage_labels": STAGE_LABELS,
            "closed_reasons": tracking.CLOSED_REASONS, "skip_reasons": tracking.SKIP_REASONS,
            "role_labels": ROLE_LABELS,
        }

    @app.get("/api/jobs")
    def jobs(view: str = "active", q: str = "", yoe: str = "", days: int = 0, store: JobStore = Depends(db)):
        if view not in JOB_VIEWS:
            raise BadRequest(f"unknown view {view!r}")
        if yoe and yoe not in YEARS:
            raise BadRequest(f"unknown years filter {yoe!r}")
        # Posted: the date the row shows (when the job was posted, or when it was found if the source
        # gives none), from local midnight; days=1 is today only.
        if days < 0:
            raise BadRequest(f"days must be 0 (any time) or more, not {days}")
        since = datetime.combine(local_day(now()) - timedelta(days=days - 1), time.min).astimezone() if days else None
        rows = job_list(store, view, q, yoe, since)
        contacts = chosen_contacts(store, rows, config)
        return {"jobs": [_job_summary(row, contacts[row["id"]], config) for row in rows]}

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
    def stage(job_id: int, body: StageChange, store: JobStore = Depends(db)):
        job_or_404(store, job_id)
        tracking.set_stage(store, job_id, body.stage, now(), reason=body.reason, skip_reason=body.skip_reason or None,
                           skip_note=body.skip_note or "")
        store.commit()
        return _job_detail(store, store.get(job_id), config, services, profile(), now())

    @app.patch("/api/jobs/{job_id}/application")
    def application(job_id: int, change: ApplicationChange = ApplicationChange(), store: JobStore = Depends(db)):
        job_or_404(store, job_id)
        sent = change.model_fields_set
        t = now()
        me = profile()
        when = parse_datetime(change.applied_at) if change.applied_at else t
        if when is None:
            raise BadRequest(f"applied_at: not a date: {change.applied_at}")
        tracking.ensure_application(store, job_id, t)
        if "notes" in sent:
            tracking.update_notes(store, job_id, change.notes or "", t)
        if "applied" in sent:
            tracking.mark_applied(store, job_id, when if change.applied else None, t)
            reassemble(store, job_id, me, t, config)
        if "contact_id" in sent:
            _, key = company_ref(store.get(job_id)["company"])
            if change.contact_id is None or not contact_at(store, change.contact_id, key):
                raise BadRequest("that contact is not at this company")
            set_application_contact(store, job_id, change.contact_id)
            reassemble(store, job_id, me, t, config)
        if "cv_file" in sent:
            choice = change.cv_file or ""
            if choice not in ("", "none", *cv_options(config)):
                raise BadRequest(f"no CV named {choice} in {config.cv_dir}")
            set_cv_file(store, job_id, choice or None)
            reassemble(store, job_id, me, t, config)
        if "subject" in sent or "body" in sent:
            app_row = get_application(store, job_id)
            if change.draft_version is not None and change.draft_version != app_row["draft_version"]:
                raise Conflict("The draft changed since this page loaded (the daily run or another tab). "
                               "Reload before editing.")
            edit_draft(store, job_id, change.subject if change.subject is not None else app_row["subject"] or "",
                       change.body if change.body is not None else app_row["body"] or "", me, t)
        store.commit()
        return _job_detail(store, store.get(job_id), config, services, me, t)

    @app.put("/api/jobs/{job_id}/contact")
    def manual_contact(job_id: int, body: ManualContact = ManualContact(), store: JobStore = Depends(db)):
        job_or_404(store, job_id)
        t = now()
        if not (body.full_name or "").strip() and not (body.email or "").strip():
            raise BadRequest("give a name or an email")
        save_manual_contact(store, job_id, body.full_name or "", body.email or "", body.position or "", t)
        reassemble(store, job_id, profile(), t, config)
        store.commit()
        return _job_detail(store, store.get(job_id), config, services, profile(), t)

    @app.post("/api/jobs/{job_id}/company")
    def company(job_id: int, change: CompanyChange = CompanyChange(), store: JobStore = Depends(db)):
        row = job_or_404(store, job_id)
        company_row = ensure_company(store, row)
        if "is_job_board" in change.model_fields_set:
            set_job_board(store, company_row["key"], bool(change.is_job_board))
        if "domain" in change.model_fields_set:
            set_domain(store, company_row["key"], change.domain or "")
            forget_lookup(store, company_row["key"])
        store.commit()
        return _job_detail(store, store.get(job_id), config, services, profile(), now())

    @app.post("/api/jobs/{job_id}/find-contact")
    def find_contact(job_id: int, body: ContactLookup = ContactLookup(), store: JobStore = Depends(db)):
        row = job_or_404(store, job_id)
        finder, note = services.finder()
        if finder is None:
            raise BadRequest(note or "no lookup service configured")
        result = finder.lookup(store, row, now(), use_claude=body.use_claude, force=body.force)
        store.commit()
        detail = _job_detail(store, store.get(job_id), config, services, profile(), now())
        detail["lookup"] = result.__dict__
        return detail

    @app.post("/api/contacts/{contact_id}/verify")
    def verify(contact_id: int, store: JobStore = Depends(db)):
        finder, note = services.finder()
        if finder is None or finder.hunter is None:
            raise BadRequest("verifying needs HUNTER_API_KEY")
        status = verify_email(store, finder.hunter, contact_id)
        store.commit()
        return {"email_status": status}

    @app.post("/api/jobs/{job_id}/draft")
    def draft(job_id: int, store: JobStore = Depends(db)):
        job_or_404(store, job_id)
        writer, note = (None, None) if config.pitch_mode != "ai" else services.writer()
        if config.pitch_mode == "ai" and writer is None:
            raise BadRequest(note or "drafting is off")
        try:
            draft_for_job(store, job_id, writer, profile(), config, now(), force=True)
        except AppError:
            raise
        except Exception as exc:  # the model failed: say so on the page
            raise UpstreamError(f"Drafting failed: {error_line(exc)}") from exc
        store.commit()
        return _job_detail(store, store.get(job_id), config, services, profile(), now())

    @app.post("/api/jobs/{job_id}/tailor")
    def tailor(job_id: int, body: TailorRequest = TailorRequest(), store: JobStore = Depends(db)):
        job_or_404(store, job_id)
        writer, note = services.cv_writer()
        if writer is None:
            raise BadRequest(note or "tailoring is off")
        try:
            result = tailor_for_job(store, job_id, writer, paths.profile_file, config, now(), builder=services.build_pdf,
                                    replace_edits=body.replace_edits)
        except AppError:
            raise
        except Exception as exc:  # the model failed: say so on the page (build.py's own failures are a BuildError)
            raise UpstreamError(f"Tailoring failed: {error_line(exc)}") from exc
        detail = _job_detail(store, store.get(job_id), config, services, profile(), now())
        detail["tailored"] = result
        return detail

    @app.get("/api/jobs/{job_id}/cv-text")
    def cv_text(job_id: int, store: JobStore = Depends(db)):
        """The text behind the job's CV (versions/<name>.md), to edit, and the lines that say more than the profile."""
        row = job_or_404(store, job_id)
        company, _ = clean_company_name(row["company"])
        source = version_of(config, company, get_application(store, job_id))
        if source is None:
            return JSONResponse({"error": "This job uses the general CV: tailor one first"}, status_code=404)
        text = source.read_text()
        folder = Path(config.resume_dir).expanduser().resolve()
        return {"source": str(source.relative_to(folder)), "text": text,
                "checks": check_version(text, paths.profile_file)}

    @app.put("/api/jobs/{job_id}/cv-text")
    def save_cv_text(job_id: int, body: CvText, store: JobStore = Depends(db)):
        """Save your edit and rebuild the PDF with build.py. No model: what you save is what prints."""
        job_or_404(store, job_id)
        try:
            result = save_version(store, job_id, config, paths.profile_file, now(), body.text,
                                  builder=services.build_pdf)
        except AppError:
            raise
        except Exception as exc:  # build.py could not run: say so on the page
            raise UpstreamError(f"Rebuilding the PDF failed: {error_line(exc)}") from exc
        detail = _job_detail(store, store.get(job_id), config, services, profile(), now())
        detail["cv_saved"] = result
        return detail

    @app.post("/api/jobs/{job_id}/cover")
    def cover(job_id: int, store: JobStore = Depends(db)):
        job_or_404(store, job_id)
        writer, note = services.cover_writer()
        if writer is None:
            raise BadRequest(note or "cover letters are off")
        try:
            cover_for_job(store, job_id, writer, paths.profile_file, config, now())
        except AppError:
            raise
        except Exception as exc:  # the model failed, or the folder cannot be written: say so on the page
            raise UpstreamError(f"Writing the cover letter failed: {error_line(exc)}") from exc
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
    def send(job_id: int, body: SendRequest = SendRequest(), store: JobStore = Depends(db)):
        job_or_404(store, job_id)
        account = services.account()
        if account is None:
            raise BadRequest("Gmail is not set up: add GMAIL_ADDRESS and GMAIL_APP_PASSWORD to .env")
        me = profile()
        account = MailAccount(account.address, account.password, me.name)
        result = send_for_job(store, job_id, services.sender(account), account, me, config, now(),
                              draft_version=body.draft_version, test=body.test, confirm=set(body.confirm or []),
                              seq=body.seq)
        detail = _job_detail(store, store.get(job_id), config, services, me, now())
        detail["sent"] = result
        return detail

    @app.post("/api/inbox/check")
    def inbox_check(store: JobStore = Depends(db)):
        account = services.account()
        if account is None:
            raise BadRequest("Gmail is not set up: add GMAIL_ADDRESS and GMAIL_APP_PASSWORD to .env")
        inbox = None
        try:
            inbox = services.inbox(account) if has_mail(store) else None
            result = check_inbox(store, account, config, now(), inbox=inbox)
        except AppError:
            raise
        except Exception as exc:  # Gmail refused the login or the scan failed: say so on the page
            raise UpstreamError(f"Checking Gmail failed: {error_line(exc)}") from exc
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


def _job_summary(row: sqlite3.Row, contact: sqlite3.Row | None, config: OutreachConfig) -> dict:
    """A row of the job list; `contact` is its chosen_contact (looked up for the whole list at once)."""
    reasons = _reasons(row, "eligibility_reasons_json")
    company, _ = clean_company_name(row["company"])
    return {
        "id": row["id"], "title": row["title"], "company": company, "status": row["status"],
        "eligibility": row["eligibility"], "reason": reasons[0] if reasons else "", "fit": row["fit_score"],
        "required_yoe": row["required_yoe"], "salary": salary_text(row), "posted_at": row["posted_at"], "first_seen": row["first_seen"],
        "report_date": row["report_date"], "source": row["source"],
        "apply_url": row["application_url"] or row["source_url"],
        "stage": row["stage"] or "new", "closed_reason": row["closed_reason"], "skip_reason": row["skip_reason"],
        "fit_grade": grade_of(row), "has_draft": bool(row["has_draft"]),
        "draft_blocked": bool(row["draft_blocked"]), "emailed_at": row["emailed_at"], "applied_at": row["applied_at"],
        "has_cv": bool(row["has_cv"]), "has_cover": bool(row["has_cover"]),
        "replied_at": row["replied_at"], "next_follow_up_at": row["next_follow_up_at"],
        "reached_out_at": tracking.reached_out_at(row) if row["stage"] not in (None, NEW, SAVED) else None,
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
    company = job_company(store, row)
    targets, why = targets_for(company["size_range"], company["size_count"], config)
    contacts = rank_contacts(company_contacts(store, company["key"]), targets)
    chosen = chosen_contact(store, row, config)
    app = get_application(store, row["id"])
    sent = mail_for_job(store, row["id"])
    preview, preview_error = None, None
    account = services.account()
    if app and app["body"]:
        try:
            out = outgoing(store, row["id"], False, account or MailAccount("you@gmail.com", ""), profile, config)
            preview = {"kind": out.kind, "seq": out.seq, "to": out.to, "subject": out.subject, "body": out.body,
                       "guessed": out.guessed, "words": word_count(out.body)}
        except SendError as exc:
            preview_error = str(exc)
    earlier = company_contacted(store, company["key"], row["id"])
    sightings = store.sightings_for([row["id"]])[row["id"]]
    return {
        "job": {
            "id": row["id"], "title": row["title"], "company": company["name"], "status": row["status"],
            "eligibility": row["eligibility"], "eligibility_reasons": _reasons(row, "eligibility_reasons_json"),
            "relevance": row["relevance"], "relevance_reasons": _reasons(row, "relevance_reasons_json"),
            "fit": row["fit_score"], "skills": _reasons(row, "skills_json"), "salary": salary_text(row),
            "remote_status": row["remote_status"], "location": row["location_raw"],
            "employment_type": row["employment_type"], "required_yoe": row["required_yoe"],
            "posted_at": row["posted_at"], "first_seen": row["first_seen"], "report_date": row["report_date"],
            "apply_url": row["application_url"] or row["source_url"], "description": row["description"],
            "reject_reason": row["reject_reason"],
            "ai_check": json.loads(row["ai_check_json"]) if row["ai_check_json"] else None,
            "fit_grade": grade_of(row),
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
        "events": [dict(e) for e in events_for(store, row["id"])],
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
