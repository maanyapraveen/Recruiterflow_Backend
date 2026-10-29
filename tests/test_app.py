import sqlite3

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("RECRUITER_DB", str(tmp_path / "test.db"))
    from app.main import app
    with TestClient(app) as c:   # `with` triggers the lifespan -> creates tables
        c.post("/seed")
        yield c


@pytest.fixture()
def empty_client(tmp_path, monkeypatch):
    monkeypatch.setenv("RECRUITER_DB", str(tmp_path / "empty.db"))
    from app.main import app
    with TestClient(app) as c:
        yield c


def cand_body(**kw):
    body = dict(name="Test Person", skills=["alpha"], experience_years=5,
                availability="Immediate", traits=[])
    body.update(kw)
    return body


def job_body(**kw):
    body = dict(title="Test Job", required_skills=["alpha"], min_experience_years=5, culture_keywords=[])
    body.update(kw)
    return body


def job_id(c, title):
    return next(j["id"] for j in c.get("/jobs").json() if j["title"] == title)


def cand_id(c, name):
    return next(x["id"] for x in c.get("/candidates").json() if x["name"] == name)


# ---------------- original behaviour (kept) ----------------
def test_seed_is_idempotent(client):
    assert client.post("/seed").json() == {"candidates": 0, "jobs": 0}
    assert len(client.get("/candidates").json()) == 15
    assert len(client.get("/jobs").json()) == 6


def test_sherlock_tops_backend_detective(client):
    body = client.get(f"/jobs/{job_id(client, 'Backend Detective')}/matches").json()
    assert body["matches"][0]["name"] == "Sherlock H."
    assert body["matches"][0]["reason"]


def test_michael_s_best_job_is_sales_engineer(client):
    body = client.get(f"/candidates/{cand_id(client, 'Michael S.')}/matches").json()
    assert body["matches"][0]["title"] == "Sales Engineer"


def test_available_only_filters_not_looking(client):
    jid = job_id(client, "Sales Engineer")
    everyone = client.get(f"/jobs/{jid}/matches").json()["matches"]
    ready = client.get(f"/jobs/{jid}/matches?available_only=true").json()["matches"]
    assert any(m["availability"] == "Not looking" for m in everyone)
    assert all(m["availability"] != "Not looking" for m in ready)


def test_new_candidate_is_matched_immediately(client):
    r = client.post("/candidates", json=dict(
        name="New Hire", skills=["Deduction", "Forensics"], experience_years=6,
        availability="Immediate", traits=["analytical"]))
    assert r.status_code == 201
    names = [m["name"] for m in client.get(f"/jobs/{job_id(client, 'Backend Detective')}/matches").json()["matches"]]
    assert "New Hire" in names


def test_duplicates_and_missing_rows(client):
    dup = dict(name="Sherlock H.", skills=["x"], experience_years=1, availability="Immediate")
    assert client.post("/candidates", json=dup).status_code == 409
    assert client.post("/jobs", json=job_body(title="Backend Detective")).status_code == 409
    assert client.get("/jobs/9999/matches").status_code == 404
    assert client.post("/candidates", json=cand_body(experience_years=-1)).status_code == 422


# ---------------- seed-data sanity after the formula change ----------------
def test_seed_rankings_remain_sensible(client):
    top = lambda title: client.get(f"/jobs/{job_id(client, title)}/matches").json()["matches"][0]["name"]
    assert top("Incident Commander") == "Olivia P."       # 3/3 skills beats 2/3
    assert top("Developer Relations Lead") == "Elle W."   # 2/2 skills, energetic<-optimistic synonym


def test_synonym_visible_in_seed_reason(client):
    ms = client.get(f"/jobs/{job_id(client, 'Incident Commander')}/matches").json()["matches"]
    katniss = next(m for m in ms if m["name"] == "Katniss E.")
    assert "calm-under-pressure (via resilient)" in katniss["reason"]
    assert katniss["breakdown"]["culture"] == 1.0


# ---------------- 2A/2B: blank skills + normalisation over HTTP ----------------
@pytest.mark.parametrize("skills", [[""], ["   "], ["\t"], ["valid", "   "], []])
def test_candidate_rejects_blank_or_empty_skills(empty_client, skills):
    assert empty_client.post("/candidates", json=cand_body(skills=skills)).status_code == 422


@pytest.mark.parametrize("skills", [[""], ["   "], ["valid", " "], []])
def test_job_rejects_blank_or_empty_required_skills(empty_client, skills):
    assert empty_client.post("/jobs", json=job_body(required_skills=skills)).status_code == 422


def test_blank_traits_and_keywords_are_rejected_not_dropped(empty_client):
    assert empty_client.post("/candidates", json=cand_body(traits=["  "])).status_code == 422
    assert empty_client.post("/jobs", json=job_body(culture_keywords=[" "])).status_code == 422


def test_comma_inside_a_skill_is_rejected(empty_client):
    assert empty_client.post("/candidates", json=cand_body(skills=["python, java"])).status_code == 422


def test_skills_are_normalised_consistently(empty_client):
    r = empty_client.post("/candidates", json=cand_body(
        skills=["Public  Speaking", "time_management", "Python", "python "]))
    assert r.status_code == 201
    assert r.json()["skills"] == ["public-speaking", "python", "time-management"]  # stored sorted, deduped


def test_differently_spelled_skills_still_match_end_to_end(empty_client):
    empty_client.post("/jobs", json=job_body(required_skills=["public_speaking", "PYTHON"]))
    empty_client.post("/candidates", json=cand_body(skills=["Public  Speaking", "python"]))
    m = empty_client.get("/jobs/1/matches").json()["matches"]
    assert len(m) == 1 and m[0]["breakdown"]["skill"] == 1.0


# ---------------- 2D: availability input ----------------
@pytest.mark.parametrize("raw,stored", [
    ("immediate", "Immediate"), ("IMMEDIATE", "Immediate"), ("Immediate", "Immediate"),
    ("2 weeks", "2 weeks"), ("2_weeks", "2 weeks"), ("not looking", "Not looking"), ("NOT_LOOKING", "Not looking"),
])
def test_availability_is_case_insensitive_and_stored_canonically(empty_client, raw, stored):
    r = empty_client.post("/candidates", json=cand_body(availability=raw))
    assert r.status_code == 201 and r.json()["availability"] == stored


@pytest.mark.parametrize("bad", ["soon", "", "3 weeks", None, 5])
def test_unknown_availability_is_422(empty_client, bad):
    assert empty_client.post("/candidates", json=cand_body(availability=bad)).status_code == 422


def test_database_also_refuses_unknown_availability(empty_client):
    from app.database import connect
    conn = connect()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO candidates (name, experience_years, availability) VALUES ('x', 1, 'soon')")
    finally:
        conn.close()


# ---------------- 2C/2E: targeted lookups + GET by id ----------------
def test_get_candidate_and_job_by_id(client):
    cid, jid = cand_id(client, "Sherlock H."), job_id(client, "Backend Detective")
    c, j = client.get(f"/candidates/{cid}"), client.get(f"/jobs/{jid}")
    assert c.status_code == 200 and c.json()["name"] == "Sherlock H."
    assert "deduction" in c.json()["skills"] and "analytical" in c.json()["traits"]
    assert j.status_code == 200 and j.json()["title"] == "Backend Detective"
    assert j.json()["min_experience_years"] == 3


def test_get_by_id_returns_404_when_missing(client):
    assert client.get("/candidates/9999").status_code == 404
    assert client.get("/jobs/9999").status_code == 404
    assert client.get("/candidates/9999/matches").status_code == 404


def test_repo_getters_return_none_when_missing(client):
    from app import database as repo
    from app.database import connect
    conn = connect()
    try:
        assert repo.get_candidate(conn, 9999) is None and repo.get_job(conn, 9999) is None
        assert repo.get_candidate(conn, 1)["id"] == 1 and repo.get_job(conn, 1)["id"] == 1
    finally:
        conn.close()


def test_post_handlers_no_longer_load_every_row(empty_client, monkeypatch):
    from app import database as repo

    def boom(*a, **k):
        raise AssertionError("POST must use a targeted lookup, not list_*()")
    monkeypatch.setattr(repo, "list_candidates", boom)
    monkeypatch.setattr(repo, "list_jobs", boom)
    assert empty_client.post("/candidates", json=cand_body()).status_code == 201
    assert empty_client.post("/jobs", json=job_body()).status_code == 201


# ---------------- 1C: tie-break policy ("closest fit wins") ----------------
def test_tie_breaks_prefer_experience_closest_to_the_minimum(empty_client):
    # Names are alphabetical in the OPPOSITE order of the expected result, and 'more experience
    # first' (the old rule) would give 12,8,6 - so this fails under both wrong policies.
    for name, yrs in [("Aaa twelve", 12), ("Bbb eight", 8), ("Ccc six", 6)]:
        empty_client.post("/candidates", json=cand_body(name=name, experience_years=yrs))
    empty_client.post("/jobs", json=job_body(min_experience_years=5))     # job added AFTER candidates
    ms = empty_client.get("/jobs/1/matches").json()["matches"]
    assert len({m["score"] for m in ms}) == 1                              # a genuine three-way tie
    assert [m["name"] for m in ms] == ["Ccc six", "Bbb eight", "Aaa twelve"]


def test_tie_break_is_consistent_in_the_reverse_direction(empty_client):
    empty_client.post("/candidates", json=cand_body(name="Twelve", experience_years=12))
    for title, minimum in [("Aaa needs 5", 5), ("Bbb needs 10", 10)]:
        empty_client.post("/jobs", json=job_body(title=title, min_experience_years=minimum))
    ms = empty_client.get("/candidates/1/matches").json()["matches"]
    assert len({m["score"] for m in ms}) == 1
    assert [m["title"] for m in ms] == ["Bbb needs 10", "Aaa needs 5"]    # closest requirement first


def test_overqualified_candidate_ranks_below_comfortable_fit(empty_client):
    for name, yrs in [("Aaa veteran", 20), ("Bbb mid", 6)]:
        empty_client.post("/candidates", json=cand_body(name=name, experience_years=yrs))
    empty_client.post("/jobs", json=job_body(min_experience_years=2))
    ms = empty_client.get("/jobs/1/matches").json()["matches"]
    assert [m["name"] for m in ms] == ["Bbb mid", "Aaa veteran"]
    assert ms[0]["score"] > ms[1]["score"]


def test_ranking_is_deterministic_across_calls(client):
    jid = job_id(client, "Sales Engineer")
    first = client.get(f"/jobs/{jid}/matches").json()
    assert all(client.get(f"/jobs/{jid}/matches").json() == first for _ in range(3))


# ---------------- stored matches stay in sync with the algorithm ----------------
def test_rebuild_restores_all_matches(client):
    from app.database import connect
    conn = connect()
    before = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
    with conn:
        conn.execute("DELETE FROM matches")
    conn.close()
    assert client.get(f"/jobs/{job_id(client, 'Backend Detective')}/matches").json()["matches"] == []
    assert client.post("/admin/rebuild-matches").json() == {"matches": before}
    assert client.get(f"/jobs/{job_id(client, 'Backend Detective')}/matches").json()["matches"][0]["name"] == "Sherlock H."


# ===== Consolidated from original regression suite =====

import itertools

import pytest

from app import matcher as matching
from app.matcher import (CULTURE_SYNONYMS, W_CULTURE, W_EXP, W_SKILL, CandidateProfile,
                          JobProfile, canonical_availability, culture_score, experience_score,
                          match_culture, score_match)


def cand(**kw):
    base = dict(id=1, name="X", experience_years=5, availability="Immediate",
                skills=frozenset({"a", "b"}), traits=frozenset())
    base.update(kw)
    return CandidateProfile(**base)


def job(**kw):
    base = dict(id=1, title="J", min_experience_years=3,
                required_skills=frozenset({"a", "b"}), culture_keywords=frozenset())
    base.update(kw)
    return JobProfile(**base)


# ---------------- original behaviour (kept) ----------------
def test_no_skill_overlap_is_not_a_match():
    assert score_match(cand(skills=frozenset({"z"})), job()) is None


def test_full_skill_match_beats_partial():
    assert score_match(cand(), job()).score > score_match(cand(skills=frozenset({"a"})), job()).score


def test_experience_shortfall_is_proportional():
    assert experience_score(1, 4) == 0.25
    assert experience_score(4, 4) == 1.0


def test_overqualification_discount_is_capped():
    assert experience_score(20, 2) == 0.8


def test_not_looking_ranks_below_identical_available_candidate():
    assert score_match(cand(availability="Not looking"), job()).score < score_match(cand(), job()).score


def test_reason_mentions_missing_skill():
    assert "missing b" in score_match(cand(skills=frozenset({"a"})), job()).reason


# ---------------- 1A: skill coverage drives the ranking ----------------
def test_weights_sum_to_one():
    assert W_SKILL + W_EXP + W_CULTURE == pytest.approx(1.0)


def test_better_skill_coverage_outranks_weaker_coverage_with_better_fit():
    """Regression. Under the old additive formula this scored A=52.5 < B=60.0."""
    j = job(required_skills=frozenset("abc"), min_experience_years=4,
            culture_keywords=frozenset({"x", "y"}))
    a = score_match(cand(skills=frozenset("ab"), experience_years=2, traits=frozenset()), j)      # 2/3 skills, short exp, no culture
    b = score_match(cand(skills=frozenset("a"), experience_years=5, traits=frozenset({"x", "y"})), j)  # 1/3 skills, perfect exp+culture
    assert a.score > b.score


def test_score_rises_with_coverage_when_everything_else_is_equal():
    skills = list("abcd")
    j = job(required_skills=frozenset(skills))
    scores = [score_match(cand(skills=frozenset(skills[:k])), j).score for k in range(1, 5)]
    assert scores == sorted(scores) and len(set(scores)) == 4


def test_perfect_and_floor_scores():
    j = job(culture_keywords=frozenset({"x"}))
    assert score_match(cand(traits=frozenset({"x"})), j).score == 100.0
    # full skills but zero experience and no culture: only the skill weight remains
    floor = score_match(cand(experience_years=0), job(culture_keywords=frozenset({"x"})))
    assert floor.score == pytest.approx(100 * W_SKILL)


@pytest.mark.parametrize("avail,years,n_skills,traits", list(itertools.product(
    ["Immediate", "2 weeks", "Not looking"], [0, 1, 3, 50], [1, 2, 3], [frozenset(), frozenset({"x"})])))
def test_scores_always_within_0_to_100(avail, years, n_skills, traits):
    j = job(required_skills=frozenset("abc"), culture_keywords=frozenset({"x"}))
    r = score_match(cand(availability=avail, experience_years=years,
                         skills=frozenset("abc"[:n_skills]), traits=traits), j)
    assert 0 < r.score <= 100


def test_scoring_is_deterministic():
    j = job(culture_keywords=frozenset({"x", "y"}))
    c = cand(traits=frozenset({"x"}))
    assert score_match(c, j) == score_match(c, j)


# ---------------- 1B: culture synonyms ----------------
def test_culture_direct_match():
    assert match_culture({"decisive"}, {"decisive"}) == [("decisive", "decisive")]


@pytest.mark.parametrize("keyword,trait", [
    ("calm-under-pressure", "calm"), ("calm-under-pressure", "resilient"),
    ("persistent", "tenacious"), ("enthusiastic", "optimistic"),
    ("organized", "detail-oriented"), ("energetic", "enthusiastic"),
])
def test_culture_synonym_match(keyword, trait):
    assert match_culture({trait}, {keyword}) == [(keyword, trait)]


def test_synonyms_are_directed():
    assert match_culture({"persistent"}, {"tenacious"}) == []   # only keyword->trait is defined


def test_culture_no_match():
    assert match_culture({"blunt", "rigid"}, {"decisive"}) == []
    assert culture_score(cand(traits=frozenset({"blunt"})), job(culture_keywords=frozenset({"decisive"}))) == 0.0


def test_no_keywords_means_no_penalty():
    assert culture_score(cand(), job(culture_keywords=frozenset())) == 1.0


def test_one_trait_cannot_satisfy_two_keywords():
    syn = {"a": frozenset({"x"}), "b": frozenset({"x"})}
    assert len(match_culture({"x"}, {"a", "b"}, syn)) == 1


def test_matching_is_order_independent_and_maximal():
    # 'a' can only use x; 'b' can use x or y. A greedy pass that gave b the x would score 1, not 2.
    syn = {"a": frozenset({"x"}), "b": frozenset({"x", "y"})}
    assert len(match_culture({"x", "y"}, {"a", "b"}, syn)) == 2
    assert len(match_culture({"y", "x"}, {"b", "a"}, syn)) == 2


def test_exact_match_preferred_over_synonym():
    assert match_culture({"calm", "calm-under-pressure"}, {"calm-under-pressure"}) == \
        [("calm-under-pressure", "calm-under-pressure")]


def test_synonym_table_is_normalised_and_has_required_entries():
    assert CULTURE_SYNONYMS["calm-under-pressure"] == {"calm", "resilient"}
    assert CULTURE_SYNONYMS["persistent"] == {"tenacious"}
    assert CULTURE_SYNONYMS["enthusiastic"] == {"optimistic"}
    assert CULTURE_SYNONYMS["organized"] == {"detail-oriented"}
    assert all(k == k.strip().lower() and " " not in k for k in CULTURE_SYNONYMS)


def test_reason_shows_synonym_used():
    r = score_match(cand(traits=frozenset({"calm"})), job(culture_keywords=frozenset({"calm-under-pressure"})))
    assert "calm-under-pressure (via calm)" in r.reason


# ---------------- 1C: over-qualification policy ----------------
def test_overqualified_candidate_scores_lower_than_comfortable_fit():
    j = job(min_experience_years=2)
    assert score_match(cand(experience_years=6), j).score > score_match(cand(experience_years=20), j).score


@pytest.mark.parametrize("years,expected", [(2, 1.0), (6, 1.0), (7, 0.975), (100, 0.8)])
def test_experience_boundaries(years, expected):
    assert experience_score(years, 2) == pytest.approx(expected)


def test_equal_experience_fit_means_equal_score_inside_the_free_zone():
    j = job(min_experience_years=5)
    assert score_match(cand(experience_years=6), j).score == score_match(cand(experience_years=12), j).score


# ---------------- 1D: availability is strict ----------------
@pytest.mark.parametrize("raw,canon", [
    ("Immediate", "Immediate"), ("immediate", "Immediate"), ("IMMEDIATE", "Immediate"),
    (" 2 weeks ", "2 weeks"), ("2_weeks", "2 weeks"), ("2-weeks", "2 weeks"),
    ("not looking", "Not looking"), ("NOT_LOOKING", "Not looking"),
])
def test_canonical_availability(raw, canon):
    assert canonical_availability(raw) == canon


@pytest.mark.parametrize("bad", ["soon", "", "   ", "3 weeks", None, 5])
def test_canonical_availability_rejects_unknown(bad):
    with pytest.raises(ValueError):
        canonical_availability(bad)


def test_score_match_raises_on_unknown_availability_instead_of_guessing():
    with pytest.raises(ValueError, match="Unknown availability"):
        score_match(cand(availability="whenever"), job())


def test_every_canonical_availability_has_a_factor():
    assert set(matching.AVAILABILITY_FACTOR) == {"Immediate", "2 weeks", "Not looking"}


# ---------------- 2B: normalisation applies inside matching too ----------------
def test_matching_normalises_both_sides():
    c = cand(skills=frozenset({"Public_Speaking", "Python"}))
    j = job(required_skills=frozenset({"public  speaking", "python"}))
    assert score_match(c, j).skill_score == 1.0


# ===== Consolidated from original regression suite =====

import pytest

from app.matcher import clean_terms, normalize_term


@pytest.mark.parametrize("raw,expected", [
    ("Public  Speaking", "public-speaking"),
    ("time_management", "time-management"),
    ("Python", "python"),
    ("  Rapid \t Prototyping  ", "rapid-prototyping"),
    ("a__b  _c", "a-b-c"),
    ("already-hyphenated", "already-hyphenated"),
])
def test_normalize_term(raw, expected):
    assert normalize_term(raw) == expected


def test_normalisation_is_idempotent():
    for raw in ["Public  Speaking", "time_management", "Python"]:
        once = normalize_term(raw)
        assert normalize_term(once) == once


def test_clean_terms_dedupes_and_keeps_order():
    assert clean_terms(["Python", "python ", "Public  Speaking", "public_speaking"], "skills") == \
        ["python", "public-speaking"]


@pytest.mark.parametrize("bad", [[""], ["   "], ["ok", "  "], ["_"], ["-"], ["\t"]])
def test_clean_terms_rejects_blank_entries(bad):
    with pytest.raises(ValueError, match="blank"):
        clean_terms(bad, "skills")


def test_clean_terms_rejects_commas():
    with pytest.raises(ValueError, match="comma"):
        clean_terms(["python, java"], "skills")


def test_clean_terms_allows_empty_list_itself():
    # emptiness of the list is enforced by the model (min_length=1) where it is prohibited
    assert clean_terms([], "traits") == []
