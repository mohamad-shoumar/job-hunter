"""SQLite persistence. The database is the system's memory; reports are output.

  schema.py  the tables, and the numbered migrations (PRAGMA user_version)
  jobs.py    JobStore (the connection) and its methods for jobs, sightings, runs, kv
"""

from .jobs import JobStore, job_ats_key, row_to_job

__all__ = ["JobStore", "job_ats_key", "row_to_job"]
