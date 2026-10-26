"""The schema and its migrations: an older database ends up like a new one, and a migration runs once."""

import sqlite3

import pytest

from jobhunter.store import JobStore
from jobhunter.store.schema import LATEST_VERSION, MIGRATIONS, user_version

from .conftest import fixture_text

# Version 0: the schema before numbered migrations, with none of the columns added later.
V0 = fixture_text("schema_v0.sql")
# A version-0 database made after some of those columns, before the others.
V0_SOME = V0 + "".join(f"ALTER TABLE {table} ADD COLUMN {column} TEXT;\n" for table, column in [
    ("jobs", "report_date"), ("jobs", "ai_check_json"),
    ("applications", "cv_file"), ("applications", "cv_tailored_json"), ("applications", "cover_letter_json"),
])
# From before outreach: only runs, jobs and sightings.
V0_NO_OUTREACH = V0.split("-- Outreach and tracking")[0]


def shape(conn: sqlite3.Connection) -> tuple[dict, dict]:
    """({table: (columns by name, indexes by name)}, {index: its SQL}). Positions are left out: an added
    column comes last, and an index made by a migration comes later than in a new database."""
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
    found = {}
    for table in tables:
        columns = {r[1]: (r[2], r[3], r[4], r[5]) for r in conn.execute(f"PRAGMA table_info({table})")}
        indexes = {r[1]: (r[2], r[3], r[4]) for r in conn.execute(f"PRAGMA index_list({table})")}
        found[table] = (columns, indexes)
    index_sql = {r[0]: r[1] for r in conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'index'")}
    return found, index_sql


def old_database(tmp_path, script: str):
    db = tmp_path / "old.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript(script)
    conn.execute("INSERT INTO runs (started_at) VALUES ('2026-09-01T08:00:00+00:00')")
    conn.commit()
    conn.close()
    return db


@pytest.mark.parametrize("script", [V0, V0_SOME, V0_NO_OUTREACH], ids=["none_added", "some_added", "no_outreach"])
def test_an_old_database_migrates_to_the_same_schema_as_a_new_one(tmp_path, script):
    db = old_database(tmp_path, script)
    assert user_version(sqlite3.connect(db)) == 0
    store = JobStore(db)
    assert shape(store.conn) == shape(JobStore(":memory:").conn)
    assert user_version(store.conn) == LATEST_VERSION
    assert store.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1  # the rows stay
    assert store.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_migrating_twice_changes_nothing(tmp_path):
    def state(conn):
        return shape(conn), user_version(conn), [tuple(r) for r in conn.execute("SELECT * FROM sqlite_master")]

    db = old_database(tmp_path, V0)
    JobStore(db).close()
    conn = sqlite3.connect(db)
    before = state(conn)
    conn.close()
    store = JobStore(db)
    assert state(store.conn) == before
    # Run again by hand (a migration cut short before the version was saved): still nothing changes.
    for migration in MIGRATIONS:
        migration(store.conn)
    assert shape(store.conn) == before[0]


def test_a_new_database_is_at_the_latest_version(tmp_path):
    assert user_version(JobStore(":memory:").conn) == LATEST_VERSION
    store = JobStore(tmp_path / "data" / "jobs.sqlite")
    assert user_version(store.conn) == LATEST_VERSION
    assert "jobs_report_date" in {r[1] for r in store.conn.execute("PRAGMA index_list(jobs)")}


def test_without_migrate_nothing_is_created(tmp_path):
    db = tmp_path / "jobs.sqlite"
    store = JobStore(db, migrate=False)
    assert store.conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] == 0
    assert user_version(store.conn) == 0
