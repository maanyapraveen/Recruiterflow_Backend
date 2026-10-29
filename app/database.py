"""SQLite plumbing: connections, PRAGMAs, schema bootstrap."""
import os
import sqlite3
from pathlib import Path
from typing import Iterator

SCHEMA_SQL = r"""-- Hand-written DDL. Idempotent, so it is safe to run on every startup.

CREATE TABLE IF NOT EXISTS candidates (
    id               INTEGER PRIMARY KEY,
    name             TEXT    NOT NULL UNIQUE,
    experience_years INTEGER NOT NULL CHECK (experience_years >= 0),
    availability     TEXT    NOT NULL CHECK (availability IN ('Immediate', '2 weeks', 'Not looking')),
    quirk            TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    id                   INTEGER PRIMARY KEY,
    title                TEXT    NOT NULL UNIQUE,
    min_experience_years INTEGER NOT NULL CHECK (min_experience_years >= 0),
    tagline              TEXT
);

-- Lookup tables: each skill / tag string is stored exactly once.
CREATE TABLE IF NOT EXISTS skills (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS tags   (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);

-- Many-to-many link tables. Composite PK = no duplicates + free index on the
-- leading column; the extra indexes below cover the reverse direction.
CREATE TABLE IF NOT EXISTS candidate_skills (
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    skill_id     INTEGER NOT NULL REFERENCES skills(id),
    PRIMARY KEY (candidate_id, skill_id)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS candidate_traits (
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    tag_id       INTEGER NOT NULL REFERENCES tags(id),
    PRIMARY KEY (candidate_id, tag_id)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS job_skills (
    job_id   INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    skill_id INTEGER NOT NULL REFERENCES skills(id),
    PRIMARY KEY (job_id, skill_id)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS job_culture_keywords (
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id),
    PRIMARY KEY (job_id, tag_id)
) WITHOUT ROWID;

-- A "match" is a materialised row: one (job, candidate) pair with its score,
-- the score components (so we can explain it) and a human-readable reason.
-- Pairs with zero skill overlap are never stored.
CREATE TABLE IF NOT EXISTS matches (
    job_id              INTEGER NOT NULL REFERENCES jobs(id)       ON DELETE CASCADE,
    candidate_id        INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    score               REAL    NOT NULL,   -- 0..100, final
    skill_score         REAL    NOT NULL,   -- 0..1
    experience_score    REAL    NOT NULL,   -- 0..1
    culture_score       REAL    NOT NULL,   -- 0..1
    availability_factor REAL    NOT NULL,   -- multiplier
    matched_skills      TEXT    NOT NULL,   -- comma separated
    reason              TEXT    NOT NULL,
    computed_at         TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (job_id, candidate_id)
) WITHOUT ROWID;

-- The two ranked read paths: "best candidates for job" and "best jobs for candidate".
CREATE INDEX IF NOT EXISTS idx_matches_job_rank       ON matches (job_id, score DESC);
CREATE INDEX IF NOT EXISTS idx_matches_candidate_rank ON matches (candidate_id, score DESC);

-- Reverse lookups used to find "who shares at least one skill with X".
CREATE INDEX IF NOT EXISTS idx_candidate_skills_skill ON candidate_skills (skill_id);
CREATE INDEX IF NOT EXISTS idx_job_skills_skill       ON job_skills (skill_id);
"""
DEFAULT_DB = Path(__file__).resolve().parent.parent / "recruiter.db"


def db_path() -> str:
    # Read at call time so tests can point RECRUITER_DB at a temp file.
    return os.getenv("RECRUITER_DB", str(DEFAULT_DB))


def connect() -> sqlite3.Connection:
    # check_same_thread=False: FastAPI runs sync deps/endpoints in a thread pool,
    # so one request may touch its connection from more than one thread (never
    # concurrently - each request gets its own connection).
    conn = sqlite3.connect(db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")   # off by default in SQLite!
    conn.execute("PRAGMA journal_mode = WAL")  # readers don't block the writer
    return conn


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA_SQL)
    finally:
        conn.close()


def get_conn() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency: one connection per request, always closed."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


"""All SQL lives here - hand-written, parameterised (?), no ORM.

Write path:  insert the row -> link its skills/tags -> rebuild its matches,
             all inside ONE transaction (`with conn:`), so a failure leaves nothing half-done.
Read path:   a plain indexed SELECT on the pre-computed `matches` table.
"""
import sqlite3

from . import matcher as matching



class DuplicateError(Exception):
    pass


# ---------- profile queries (correlated subqueries avoid join fan-out) ----------
_CANDIDATE_PROFILE = """
SELECT c.id, c.name, c.experience_years, c.availability, c.quirk,
       (SELECT group_concat(s.name, ',') FROM candidate_skills cs
          JOIN skills s ON s.id = cs.skill_id WHERE cs.candidate_id = c.id) AS skills,
       (SELECT group_concat(t.name, ',') FROM candidate_traits ct
          JOIN tags t ON t.id = ct.tag_id WHERE ct.candidate_id = c.id)     AS traits
FROM candidates c
"""

_JOB_PROFILE = """
SELECT j.id, j.title, j.min_experience_years, j.tagline,
       (SELECT group_concat(s.name, ',') FROM job_skills js
          JOIN skills s ON s.id = js.skill_id WHERE js.job_id = j.id)        AS skills,
       (SELECT group_concat(t.name, ',') FROM job_culture_keywords jk
          JOIN tags t ON t.id = jk.tag_id WHERE jk.job_id = j.id)            AS keywords
FROM jobs j
"""

# Candidate pruning: only look at rows sharing >= 1 skill (uses the skill indexes).
_CANDIDATES_SHARING_SKILL_WITH_JOB = """
WHERE c.id IN (SELECT cs.candidate_id FROM candidate_skills cs
               JOIN job_skills js ON js.skill_id = cs.skill_id WHERE js.job_id = ?)
"""
_JOBS_SHARING_SKILL_WITH_CANDIDATE = """
WHERE j.id IN (SELECT js.job_id FROM job_skills js
               JOIN candidate_skills cs ON cs.skill_id = js.skill_id WHERE cs.candidate_id = ?)
"""

_INSERT_MATCH = """
INSERT INTO matches (job_id, candidate_id, score, skill_score, experience_score,
                     culture_score, availability_factor, matched_skills, reason)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _split(csv):
    return sorted(csv.split(",")) if csv else []


def _to_candidate(r) -> matching.CandidateProfile:
    return matching.CandidateProfile(r["id"], r["name"], r["experience_years"], r["availability"],
                                     frozenset(_split(r["skills"])), frozenset(_split(r["traits"])))


def _to_job(r) -> matching.JobProfile:
    return matching.JobProfile(r["id"], r["title"], r["min_experience_years"],
                               frozenset(_split(r["skills"])), frozenset(_split(r["keywords"])))


def _match_params(m: matching.MatchResult):
    return (m.job_id, m.candidate_id, m.score, m.skill_score, m.experience_score,
            m.culture_score, m.availability_factor, ",".join(m.matched_skills), m.reason)


# ---------- lookup helpers ----------
def _skill_id(conn, name):
    conn.execute("INSERT OR IGNORE INTO skills (name) VALUES (?)", (name,))
    return conn.execute("SELECT id FROM skills WHERE name = ?", (name,)).fetchone()["id"]


def _tag_id(conn, name):
    conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
    return conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()["id"]


# ---------- match (re)computation ----------
def _rebuild_for_job(conn, job_id):
    job = _to_job(conn.execute(_JOB_PROFILE + " WHERE j.id = ?", (job_id,)).fetchone())
    cands = [_to_candidate(r) for r in conn.execute(
        _CANDIDATE_PROFILE + _CANDIDATES_SHARING_SKILL_WITH_JOB, (job_id,))]
    results = [m for c in cands if (m := matching.score_match(c, job))]
    conn.execute("DELETE FROM matches WHERE job_id = ?", (job_id,))
    conn.executemany(_INSERT_MATCH, [_match_params(m) for m in results])


def _rebuild_for_candidate(conn, candidate_id):
    cand = _to_candidate(conn.execute(_CANDIDATE_PROFILE + " WHERE c.id = ?", (candidate_id,)).fetchone())
    jobs = [_to_job(r) for r in conn.execute(
        _JOB_PROFILE + _JOBS_SHARING_SKILL_WITH_CANDIDATE, (candidate_id,))]
    results = [m for j in jobs if (m := matching.score_match(cand, j))]
    conn.execute("DELETE FROM matches WHERE candidate_id = ?", (candidate_id,))
    conn.executemany(_INSERT_MATCH, [_match_params(m) for m in results])


# ---------- writes ----------
def create_candidate(conn: sqlite3.Connection, data) -> int:
    try:
        with conn:  # commit on success, rollback on any exception
            cid = conn.execute(
                "INSERT INTO candidates (name, experience_years, availability, quirk) VALUES (?, ?, ?, ?)",
                (data.name, data.experience_years, data.availability, data.quirk)).lastrowid
            conn.executemany("INSERT INTO candidate_skills (candidate_id, skill_id) VALUES (?, ?)",
                             [(cid, _skill_id(conn, s)) for s in data.skills])
            conn.executemany("INSERT INTO candidate_traits (candidate_id, tag_id) VALUES (?, ?)",
                             [(cid, _tag_id(conn, t)) for t in data.traits])
            _rebuild_for_candidate(conn, cid)
        return cid
    except sqlite3.IntegrityError as e:
        if "UNIQUE" in str(e):
            raise DuplicateError(data.name) from e
        raise


def create_job(conn: sqlite3.Connection, data) -> int:
    try:
        with conn:
            jid = conn.execute(
                "INSERT INTO jobs (title, min_experience_years, tagline) VALUES (?, ?, ?)",
                (data.title, data.min_experience_years, data.tagline)).lastrowid
            conn.executemany("INSERT INTO job_skills (job_id, skill_id) VALUES (?, ?)",
                             [(jid, _skill_id(conn, s)) for s in data.required_skills])
            conn.executemany("INSERT INTO job_culture_keywords (job_id, tag_id) VALUES (?, ?)",
                             [(jid, _tag_id(conn, t)) for t in data.culture_keywords])
            _rebuild_for_job(conn, jid)
        return jid
    except sqlite3.IntegrityError as e:
        if "UNIQUE" in str(e):
            raise DuplicateError(data.title) from e
        raise


def rebuild_all_matches(conn: sqlite3.Connection) -> int:
    """Recompute every stored match from scratch. Run after changing weights, synonyms or
    any scoring rule - the matches table is a cache of the algorithm's output."""
    with conn:
        conn.execute("DELETE FROM matches")
        for r in conn.execute("SELECT id FROM jobs").fetchall():
            _rebuild_for_job(conn, r["id"])
    return conn.execute("SELECT COUNT(*) AS n FROM matches").fetchone()["n"]


# ---------- reads ----------
def _candidate_dict(r) -> dict:
    return dict(id=r["id"], name=r["name"], experience_years=r["experience_years"],
                availability=r["availability"], quirk=r["quirk"],
                skills=_split(r["skills"]), traits=_split(r["traits"]))


def _job_dict(r) -> dict:
    return dict(id=r["id"], title=r["title"], min_experience_years=r["min_experience_years"],
                tagline=r["tagline"], required_skills=_split(r["skills"]),
                culture_keywords=_split(r["keywords"]))


def list_candidates(conn) -> list:
    return [_candidate_dict(r) for r in conn.execute(_CANDIDATE_PROFILE + " ORDER BY c.id")]


def list_jobs(conn) -> list:
    return [_job_dict(r) for r in conn.execute(_JOB_PROFILE + " ORDER BY j.id")]


def get_candidate(conn, candidate_id):
    """One candidate by primary key (None if missing) - a single indexed lookup."""
    r = conn.execute(_CANDIDATE_PROFILE + " WHERE c.id = ?", (candidate_id,)).fetchone()
    return _candidate_dict(r) if r else None


def get_job(conn, job_id):
    r = conn.execute(_JOB_PROFILE + " WHERE j.id = ?", (job_id,)).fetchone()
    return _job_dict(r) if r else None


def get_job_title(conn, job_id):
    r = conn.execute("SELECT title FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return r["title"] if r else None


def get_candidate_name(conn, candidate_id):
    r = conn.execute("SELECT name FROM candidates WHERE id = ?", (candidate_id,)).fetchone()
    return r["name"] if r else None


def _breakdown(r):
    return dict(skill=r["skill_score"], experience=r["experience_score"],
                culture=r["culture_score"], availability_factor=r["availability_factor"])


def ranked_candidates_for_job(conn, job_id, limit, min_score, available_only) -> list:
    rows = conn.execute("""
        SELECT c.id AS candidate_id, c.name, c.experience_years, c.availability,
               m.score, m.skill_score, m.experience_score, m.culture_score,
               m.availability_factor, m.matched_skills, m.reason
        FROM matches m
        JOIN candidates c ON c.id = m.candidate_id
        JOIN jobs j       ON j.id = m.job_id
        WHERE m.job_id = ?
          AND m.score >= ?
          AND (? = 0 OR c.availability <> 'Not looking')
        -- Tie-break = "closest fit wins" (see matching.py): never "more experience first",
        -- because scoring discounts over-qualification.
        ORDER BY m.score DESC, m.skill_score DESC, m.experience_score DESC,
                 ABS(c.experience_years - j.min_experience_years) ASC, c.name ASC
        LIMIT ?
    """, (job_id, min_score, int(available_only), limit)).fetchall()
    return [dict(candidate_id=r["candidate_id"], name=r["name"], experience_years=r["experience_years"],
                 availability=r["availability"], score=r["score"], reason=r["reason"],
                 matched_skills=_split(r["matched_skills"]), breakdown=_breakdown(r)) for r in rows]


def ranked_jobs_for_candidate(conn, candidate_id, limit, min_score) -> list:
    rows = conn.execute("""
        SELECT j.id AS job_id, j.title, j.min_experience_years,
               m.score, m.skill_score, m.experience_score, m.culture_score,
               m.availability_factor, m.matched_skills, m.reason
        FROM matches m
        JOIN jobs j       ON j.id = m.job_id
        JOIN candidates c ON c.id = m.candidate_id
        WHERE m.candidate_id = ?
          AND m.score >= ?
        ORDER BY m.score DESC, m.skill_score DESC, m.experience_score DESC,
                 ABS(c.experience_years - j.min_experience_years) ASC, j.title ASC
        LIMIT ?
    """, (candidate_id, min_score, limit)).fetchall()
    return [dict(job_id=r["job_id"], title=r["title"], min_experience_years=r["min_experience_years"],
                 score=r["score"], reason=r["reason"], matched_skills=_split(r["matched_skills"]),
                 breakdown=_breakdown(r)) for r in rows]
