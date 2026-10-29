"""FastAPI routes and request/response validation for Recruiter Bot."""
import sqlite3
from contextlib import asynccontextmanager
from typing import Annotated, Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, BeforeValidator, Field, ValidationInfo, field_validator

from . import database as repo, seed_data as seed_records
from .database import get_conn, init_db
from .matcher import canonical_availability, clean_terms

Availability = Annotated[
    Literal["Immediate", "2 weeks", "Not looking"],
    BeforeValidator(canonical_availability),
]


class CandidateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    skills: list[str] = Field(min_length=1)
    experience_years: int = Field(ge=0, le=60)
    availability: Availability
    traits: list[str] = Field(default_factory=list)
    quirk: Optional[str] = None

    @field_validator("skills", "traits")
    @classmethod
    def _clean(cls, v, info: ValidationInfo):
        return clean_terms(v, info.field_name)


class JobIn(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    required_skills: list[str] = Field(min_length=1)
    min_experience_years: int = Field(ge=0, le=60)
    culture_keywords: list[str] = Field(default_factory=list)
    tagline: Optional[str] = None

    @field_validator("required_skills", "culture_keywords")
    @classmethod
    def _clean(cls, v, info: ValidationInfo):
        return clean_terms(v, info.field_name)


class CandidateOut(BaseModel):
    id: int
    name: str
    experience_years: int
    availability: str
    skills: list[str]
    traits: list[str]
    quirk: Optional[str] = None


class JobOut(BaseModel):
    id: int
    title: str
    min_experience_years: int
    required_skills: list[str]
    culture_keywords: list[str]
    tagline: Optional[str] = None


class ScoreBreakdown(BaseModel):
    skill: float
    experience: float
    culture: float
    availability_factor: float


class CandidateMatch(BaseModel):
    candidate_id: int
    name: str
    experience_years: int
    availability: str
    score: float
    reason: str
    matched_skills: list[str]
    breakdown: ScoreBreakdown


class JobMatch(BaseModel):
    job_id: int
    title: str
    min_experience_years: int
    score: float
    reason: str
    matched_skills: list[str]
    breakdown: ScoreBreakdown


class JobMatches(BaseModel):
    job_id: int
    title: str
    matches: list[CandidateMatch]


class CandidateMatches(BaseModel):
    candidate_id: int
    name: str
    matches: list[JobMatch]


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()  # create tables if missing
    yield


app = FastAPI(title="Recruiter Bot", version="1.0.0", lifespan=lifespan)

# NOTE: endpoints are plain `def` (not `async def`) on purpose. sqlite3 is a blocking
# driver; FastAPI runs `def` endpoints in a thread pool so they don't freeze the event loop.


# ---------------- ingestion ----------------
@app.post("/candidates", status_code=201, response_model=CandidateOut)
def add_candidate(body: CandidateIn, conn: sqlite3.Connection = Depends(get_conn)):
    try:
        cid = repo.create_candidate(conn, body)
    except repo.DuplicateError:
        raise HTTPException(409, f"Candidate '{body.name}' already exists")
    return repo.get_candidate(conn, cid)


@app.post("/jobs", status_code=201, response_model=JobOut)
def add_job(body: JobIn, conn: sqlite3.Connection = Depends(get_conn)):
    try:
        jid = repo.create_job(conn, body)
    except repo.DuplicateError:
        raise HTTPException(409, f"Job '{body.title}' already exists")
    return repo.get_job(conn, jid)


@app.post("/seed")
def seed_data(conn: sqlite3.Connection = Depends(get_conn)):
    """Load the assignment's cast of characters (safe to call repeatedly)."""
    added = {"candidates": 0, "jobs": 0}
    for item in seed_records.CANDIDATES:
        try:
            repo.create_candidate(conn, CandidateIn(**item))
            added["candidates"] += 1
        except repo.DuplicateError:
            pass
    for item in seed_records.JOBS:
        try:
            repo.create_job(conn, JobIn(**item))
            added["jobs"] += 1
        except repo.DuplicateError:
            pass
    return added


@app.post("/admin/rebuild-matches")
def rebuild_matches(conn: sqlite3.Connection = Depends(get_conn)):
    """Recompute all stored matches (use after changing the scoring rules)."""
    return {"matches": repo.rebuild_all_matches(conn)}


# ---------------- browse ----------------
@app.get("/candidates", response_model=list[CandidateOut])
def candidates(conn: sqlite3.Connection = Depends(get_conn)):
    return repo.list_candidates(conn)


@app.get("/candidates/{candidate_id}", response_model=CandidateOut)
def candidate(candidate_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    found = repo.get_candidate(conn, candidate_id)
    if found is None:
        raise HTTPException(404, "Candidate not found")
    return found


@app.get("/jobs", response_model=list[JobOut])
def jobs(conn: sqlite3.Connection = Depends(get_conn)):
    return repo.list_jobs(conn)


@app.get("/jobs/{job_id}", response_model=JobOut)
def job(job_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    found = repo.get_job(conn, job_id)
    if found is None:
        raise HTTPException(404, "Job not found")
    return found


# ---------------- matching ----------------
@app.get("/jobs/{job_id}/matches", response_model=JobMatches)
def job_matches(
    job_id: int,
    limit: int = Query(10, ge=1, le=100),
    min_score: float = Query(0, ge=0, le=100),
    available_only: bool = Query(False, description="Hide candidates who are 'Not looking'"),
    conn: sqlite3.Connection = Depends(get_conn),
):
    title = repo.get_job_title(conn, job_id)
    if title is None:
        raise HTTPException(404, "Job not found")
    return dict(job_id=job_id, title=title,
                matches=repo.ranked_candidates_for_job(conn, job_id, limit, min_score, available_only))


@app.get("/candidates/{candidate_id}/matches", response_model=CandidateMatches)
def candidate_matches(
    candidate_id: int,
    limit: int = Query(10, ge=1, le=100),
    min_score: float = Query(0, ge=0, le=100),
    conn: sqlite3.Connection = Depends(get_conn),
):
    name = repo.get_candidate_name(conn, candidate_id)
    if name is None:
        raise HTTPException(404, "Candidate not found")
    return dict(candidate_id=candidate_id, name=name,
                matches=repo.ranked_jobs_for_candidate(conn, candidate_id, limit, min_score))
