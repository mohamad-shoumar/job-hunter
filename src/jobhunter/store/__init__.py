"""SQLite persistence. The database is the system's memory; reports are output.

Every SQL statement lives in this package; the rest of the code calls the
functions here and decides what to do with the rows.

  schema.py        the tables, and the numbered migrations (PRAGMA user_version)
  jobs.py          JobStore (the connection) and its methods for jobs, sightings, runs, kv
  lists.py         jobs read with their application: the app's job list, what to grade or prepare
  applications.py  applications and events (tracking.py; the draft, CV and cover letter of a job)
  companies.py     companies and contacts (contacts.py)
  mail.py          sent_mail and mail_seen (mailer.py)
  watched.py       watched_boards and board_probes (boards.py)

The functions outside jobs.py take the JobStore as their first argument. None
of them commits: the caller decides when, so it can commit before a slow
network or model call and hold no write lock while it waits.
"""

from .jobs import JobStore, job_ats_key, row_to_job

__all__ = ["JobStore", "job_ats_key", "row_to_job"]
