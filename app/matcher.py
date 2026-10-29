"""Deterministic matching logic and shared term normalization."""
import re

_SEPARATORS = re.compile(r"[\s_]+")


def normalize_term(value: str) -> str:
    """Trim, lower-case, and turn runs of whitespace/underscores into one hyphen."""
    return _SEPARATORS.sub("-", value.strip().lower())


def clean_terms(values: list, field: str) -> list:
    """Normalise a list of terms, drop duplicates (order kept) and REJECT bad entries.

    Raises ValueError (-> HTTP 422 inside Pydantic validators) for blank entries instead of
    silently dropping them, so ["   "] can never turn into an empty list behind the caller's back.
    """
    out, seen = [], set()
    for raw in values:
        term = normalize_term(raw)
        if not any(ch.isalnum() for ch in term):
            raise ValueError(f"{field} must not contain blank entries (got {raw!r})")
        if "," in term:
            # commas are the separator we use when reading terms back out of SQLite
            raise ValueError(f"{field} entries must not contain commas (got {raw!r}); send separate items")
        if term not in seen:
            seen.add(term)
            out.append(term)
    return out


"""The matching algorithm. PURE functions only: no DB, no FastAPI.

    score = 100 * s * (W_SKILL + W_EXP * e + W_CULTURE * c) * a

    s  skill coverage   share of the job's required skills the candidate has      (0..1)
    e  experience fit   1.0 when the minimum is met; see experience_score()       (0..1)
    c  culture fit      share of the job's culture keywords the candidate meets   (0..1)
    a  availability     multiplier from AVAILABILITY_FACTOR                       (0..1)

W_SKILL + W_EXP + W_CULTURE == 1, so the score is always within 0..100.

WHY skill coverage is a MULTIPLIER (not just one more term in a sum):
the old formula was additive: 100*(0.60*s + 0.25*e + 0.15*c)*a. Experience and culture could
then add up to 40 points on their own, enough to outrank a candidate with MORE of the required
skills (2/3 skills + short experience scored 52.5; 1/3 skills + perfect fit scored 60.0).
Now every other signal is worth something only in proportion to how much of the job the
candidate can actually do.

Hard rule: zero skill overlap means "not a match" (returns None).

TIE-BREAK POLICY ("closest fit wins") - applied in SQL in database.py, in this order:
    score DESC, skill_score DESC, experience_score DESC,
    |candidate years - job minimum| ASC, then name/title ASC.
Scoring treats experience up to 3x the minimum as equally good and discounts anything beyond it,
so on a tie we must NOT prefer "more experience" (that contradicts the discount). We prefer the
candidate whose experience is closest to what the job asks for.
"""
from dataclasses import dataclass
import re



W_SKILL, W_EXP, W_CULTURE = 0.60, 0.25, 0.15

# A multiplier, not a filter: someone "not looking" may still be worth a call, just lower.
# These keys are ALSO the values allowed by the CHECK constraint in schema.sql.
AVAILABILITY_FACTOR = {"Immediate": 1.0, "2 weeks": 0.95, "Not looking": 0.60}

OVERQUALIFIED_AFTER = 3.0   # years > 3x the minimum starts to cost points
OVERQUALIFIED_FLOOR = 0.80  # ...but never below this

# Job culture keyword -> candidate traits accepted as meeting it (besides the keyword itself).
# Directed on purpose: "calm" satisfies "calm-under-pressure", not the other way round.
# Left UNMAPPED deliberately: autonomous, fast-paced, curious. No trait in our data is a
# defensible equivalent (e.g. 'improviser' is not 'autonomous'), and a wrong synonym is worse
# than a missing one. Add entries here when new traits appear in real data.
_RAW_CULTURE_SYNONYMS = {
    "calm-under-pressure": ["calm", "resilient"],
    "persistent": ["tenacious"],
    "enthusiastic": ["optimistic"],
    "organized": ["detail-oriented"],
    "energetic": ["enthusiastic", "optimistic"],
}
CULTURE_SYNONYMS = {
    normalize_term(k): frozenset(normalize_term(v) for v in vs)
    for k, vs in _RAW_CULTURE_SYNONYMS.items()
}

_AVAILABILITY_LOOKUP = {re.sub(r"[\s_-]+", " ", k.lower()): k for k in AVAILABILITY_FACTOR}


def canonical_availability(value) -> str:
    """'immediate' / 'NOT_LOOKING' / '2-weeks' -> the canonical stored spelling.
    Raises ValueError for anything unknown (never guesses a default)."""
    if isinstance(value, str):
        key = re.sub(r"[\s_-]+", " ", value.strip().lower())
        if key in _AVAILABILITY_LOOKUP:
            return _AVAILABILITY_LOOKUP[key]
    raise ValueError(f"Unknown availability {value!r}; expected one of {list(AVAILABILITY_FACTOR)}")


@dataclass(frozen=True)
class CandidateProfile:
    id: int
    name: str
    experience_years: int
    availability: str
    skills: frozenset
    traits: frozenset


@dataclass(frozen=True)
class JobProfile:
    id: int
    title: str
    min_experience_years: int
    required_skills: frozenset
    culture_keywords: frozenset


@dataclass(frozen=True)
class MatchResult:
    job_id: int
    candidate_id: int
    score: float
    skill_score: float
    experience_score: float
    culture_score: float
    availability_factor: float
    matched_skills: tuple
    reason: str


def _norm_set(values) -> frozenset:
    return frozenset(normalize_term(v) for v in values)


def skill_score(cand: CandidateProfile, job: JobProfile) -> float:
    """Fraction of the job's required skills the candidate has (0..1)."""
    required = _norm_set(job.required_skills)
    if not required:
        return 0.0
    return len(_norm_set(cand.skills) & required) / len(required)


def experience_score(years: int, min_years: int) -> float:
    """1.0 when the minimum is met; proportional below it; a small capped discount once the
    candidate has more than 3x the minimum (20 yrs for a 2-yr role)."""
    if min_years <= 0:
        return 1.0
    if years < min_years:
        return years / min_years
    ratio = years / min_years
    if ratio <= OVERQUALIFIED_AFTER:
        return 1.0
    return max(OVERQUALIFIED_FLOOR, 1.0 - 0.05 * (ratio - OVERQUALIFIED_AFTER))


def match_culture(traits, keywords, synonyms=None) -> list:
    """Pair job keywords with candidate traits, ONE-TO-ONE: a trait can satisfy at most one
    keyword and a keyword is satisfied by at most one trait. Returns sorted (keyword, trait)
    pairs.

    A keyword accepts the identical trait or any of its synonyms. This is a maximum bipartite
    matching (augmenting paths), so the result does not depend on keyword order: a greedy pass
    could spend a shared trait on the wrong keyword and lose a match. Exact matches are tried
    first so reasons read naturally.
    """
    synonyms = CULTURE_SYNONYMS if synonyms is None else synonyms
    traits, keywords = sorted(_norm_set(traits)), sorted(_norm_set(keywords))

    options = {}
    for kw in keywords:
        accepted = {kw} | set(synonyms.get(kw, ()))
        options[kw] = sorted((t for t in traits if t in accepted), key=lambda t: (t != kw, t))

    owner = {}  # trait -> keyword currently using it

    def assign(kw, seen):
        for t in options[kw]:
            if t in seen:
                continue
            seen.add(t)
            if t not in owner or assign(owner[t], seen):
                owner[t] = kw
                return True
        return False

    for kw in keywords:
        assign(kw, set())
    return sorted((kw, t) for t, kw in owner.items())


def culture_score(cand: CandidateProfile, job: JobProfile) -> float:
    """Fraction of the job's culture keywords the candidate meets (directly or by synonym).
    No keywords on the job = nothing to miss = no penalty."""
    keywords = _norm_set(job.culture_keywords)
    if not keywords:
        return 1.0
    return len(match_culture(cand.traits, keywords)) / len(keywords)


def score_match(cand: CandidateProfile, job: JobProfile) -> "MatchResult | None":
    # Strict on purpose: an unknown availability is a data bug, not something to guess about.
    try:
        a = AVAILABILITY_FACTOR[cand.availability]
    except KeyError:
        raise ValueError(
            f"Unknown availability {cand.availability!r} for candidate {cand.id}; "
            f"expected one of {list(AVAILABILITY_FACTOR)}") from None

    required = _norm_set(job.required_skills)
    matched = _norm_set(cand.skills) & required
    if not matched:
        return None

    s = skill_score(cand, job)
    e = experience_score(cand.experience_years, job.min_experience_years)
    culture_pairs = match_culture(cand.traits, job.culture_keywords)
    keywords = _norm_set(job.culture_keywords)
    c = len(culture_pairs) / len(keywords) if keywords else 1.0
    total = round(100 * s * (W_SKILL + W_EXP * e + W_CULTURE * c) * a, 2)

    return MatchResult(
        job_id=job.id,
        candidate_id=cand.id,
        score=total,
        skill_score=round(s, 4),
        experience_score=round(e, 4),
        culture_score=round(c, 4),
        availability_factor=a,
        matched_skills=tuple(sorted(matched)),
        reason=_reason(cand, job, required, matched, culture_pairs),
    )


def _reason(cand, job, required, matched, culture_pairs) -> str:
    parts = [f"{len(matched)}/{len(required)} required skills ({', '.join(sorted(matched))})"]
    missing = required - matched
    if missing:
        parts.append(f"missing {', '.join(sorted(missing))}")
    if cand.experience_years >= job.min_experience_years:
        parts.append(f"{cand.experience_years} yrs meets the {job.min_experience_years}+ yr minimum")
    else:
        parts.append(f"{cand.experience_years} yrs is short of the {job.min_experience_years}-yr minimum")
    if culture_pairs:
        shown = [kw if kw == t else f"{kw} (via {t})" for kw, t in culture_pairs]
        parts.append(f"culture fit: {', '.join(shown)}")
    if cand.availability != "Immediate":
        parts.append(f"availability: {cand.availability.lower()}")
    return "; ".join(parts)
