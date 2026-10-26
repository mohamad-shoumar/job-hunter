"""Errors whose message is shown to you as is: on the page as {"error": ...}, or printed by the CLI.

Each carries the HTTP status the web app answers with, so one handler (web/app.py) serves them all:

  BadRequest     400  the request makes no sense for the job as it is, or a value is wrong
  NotFound       404  no such job or contact
  Conflict       409  the job changed since the page loaded, or the step needs your OK first
  UpstreamError  502  the model, build.py, Hunter or Gmail failed

The modules keep their own names on top of these (tracking.TrackingError, cv.TailorError,
cover.CoverError, mailer.SendError, hunter.HunterError), so callers can still catch just theirs.
"""

from __future__ import annotations


class AppError(Exception):
    http_status = 400

    def to_dict(self) -> dict:
        """The JSON body the web app answers with."""
        return {"error": str(self)}


class BadRequest(AppError):
    http_status = 400


class NotFound(AppError):
    http_status = 404


class Conflict(AppError):
    http_status = 409


class UpstreamError(AppError):
    http_status = 502
