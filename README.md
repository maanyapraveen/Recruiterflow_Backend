# Recruiter Bot

A small FastAPI backend that stores candidate profiles and job openings in SQLite, then ranks matches in both directions. The matching algorithm is deterministic and explainable. All database access uses Python's built-in `sqlite3` and hand-written parameterized SQL; there is no ORM or query builder.

## Project structure

```text
recruiter-bot/
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI routes and Pydantic validation/response models
│   ├── database.py      # SQLite schema, connections, CRUD, match persistence and queries
│   ├── matcher.py       # normalization, culture synonyms and scoring functions
│   └── seed_data.py     # assignment's 15 candidates and 6 jobs
├── tests/
│   └── test_app.py      # consolidated regression and API tests
├── sql_detective.sql    # five Part 2 handwritten SQL answers
├── seed.sql             # standalone idempotent SQLite schema + assignment seed
├── requirements.txt
├── pytest.ini
├── README.md
└── .gitignore
```

## Windows setup (PowerShell)

From the project root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest -q
python -m uvicorn app.main:app --reload --port 8000
```

If PowerShell blocks activation, use `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` for the current terminal, then activate again. The app creates its SQLite schema at startup. Open Swagger UI at <http://127.0.0.1:8000/docs>.

## Initialize and seed

The application database defaults to `recruiter.db` in the project root. It is generated at runtime and is ignored by Git. Start the server and call the idempotent seed endpoint once:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/seed
```

It should add 15 candidates and 6 jobs to an empty database. Repeating the call adds zero duplicates. You can also run the standalone `seed.sql` script against a SQLite database using a SQLite-compatible SQL client; it creates the same schema and seed records. Do not run the standalone script against the live database unless you intentionally want to seed that database. If you use `seed.sql` to initialize a new database, start the app with `RECRUITER_DB` pointing to that same file and call `POST /admin/rebuild-matches` before reading matches, because match rows are calculated by the Python scoring code. The FastAPI app does not require a separately installed SQLite CLI.

For isolated development/testing, set `RECRUITER_DB` to a different database path before starting the app. Tests use temporary databases and should not modify your development database.

## API endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/candidates` | List candidates |
| `GET` | `/candidates/{id}` | Get one candidate (`404` if missing) |
| `POST` | `/candidates` | Create candidate (`201`; `409` duplicate) |
| `GET` | `/jobs` | List jobs |
| `GET` | `/jobs/{id}` | Get one job (`404` if missing) |
| `POST` | `/jobs` | Create job (`201`; `409` duplicate) |
| `GET` | `/jobs/{id}/matches` | Ranked candidates for a job |
| `GET` | `/candidates/{id}/matches` | Ranked jobs for a candidate |
| `POST` | `/seed` | Idempotently add the assignment's seed records |
| `POST` | `/admin/rebuild-matches` | Recompute all stored matches |

Example URLs:

```text
GET /jobs/1/matches?limit=5&min_score=20&available_only=true
GET /candidates/1/matches?limit=10&min_score=0
```

`limit` accepts 1–100. `min_score` accepts 0–100. `available_only` is supported on the job-to-candidate direction and excludes candidates whose availability is `Not looking`. Invalid request values return `422`; missing resources return `404`. Skills, traits, and culture keywords are lower-cased and normalized by trimming and replacing runs of whitespace/underscores with hyphens. Duplicate normalized terms are removed. Blank terms and comma-containing terms are rejected.

## Matching formula

For a candidate/job pair with at least one shared required skill:

`score = 100 × s × (0.60 + 0.25 × e + 0.15 × c) × a`

- `s` is skill coverage: distinct required skills matched divided by distinct required skills. The API requires at least one required skill, and a pair with no shared skill is not a match.
- `e` is experience fit: `1.0` if candidate experience meets the minimum; below the minimum it is proportional (`candidate_years / minimum_years`, with a zero-minimum edge case handled explicitly). Above three times the minimum, a capped overqualification discount applies, with a floor of `0.80`.
- `c` is culture fit: the fraction of culture keywords matched directly or through the directed `CULTURE_SYNONYMS` map. Matching is one-to-one, so one trait cannot satisfy multiple distinct keywords. No culture keywords means a fit of `1.0`.
- `a` is availability: `Immediate = 1.0`, `2 weeks = 0.95`, and `Not looking = 0.60`. Availability also accepts case/spacing/underscore variants at the API boundary; unknown values are rejected rather than assigned a fallback.
- No shared required skill means no match is stored. Explanations are computed from the actual matched/missing skills, experience fit, culture matches and availability.
- Weights sum to 1.0, and all factors are bounded, so scores remain in 0–100.

Rank order is score descending, skill coverage descending, experience fit descending, absolute distance from the job's minimum experience ascending, then candidate name or job title ascending. This “closest fit wins” tie-break avoids rewarding extra experience after the score has already discounted overqualification. After changing weights or synonyms, call `POST /admin/rebuild-matches` because match rows are persisted as a cache.

## Part 2 SQL Detective

`sql_detective.sql` contains one commented query for each of the five assignment questions. It uses the supplied `recruiters`, `job_postings`, `applicants`, and `interviews` schema. Run it in a SQLite-compatible client after creating those tables and loading the Part 2 seed data. The bonus query uses a window function to select the top recruiter by successful Final-stage placements per department.

## Tests

Run either:

```powershell
pytest -q
python -m pytest -q
```

The regression suite was consolidated into `tests/test_app.py`. Results are reported below only after running the commands in the current environment; they should be re-run on the target Windows machine after installation.

## Design trade-offs and limitations

- The normalized lookup/link tables avoid duplicate skill/tag values and support indexed overlap queries.
- Matches are persisted so reads are fast; writes and full rebuilds do more work. At this small assignment scale this is reasonable.
- Skills have equal weight and use exact matching after normalization (`js` and `javascript` remain different).
- Culture synonyms are intentionally small and hand-curated. `autonomous`, `fast-paced`, and `curious` remain unmapped because the supplied traits do not provide a defensible equivalent.
- There are no update/delete endpoints because they are not required by the brief. Add them only with transactional match rebuilding.
- Candidate names and job titles are unique; duplicate creates return `409`.

## AI tools disclosure

AI tools were used throughout the project lifecycle, including planning, implementation, debugging, testing, and documentation. They assisted with designing the project structure, refining the matching algorithm, developing and refactoring application modules, reviewing SQL queries, identifying and resolving errors, and preparing and reviewing automated tests.

The implementation was tested using the project's automated test suite, and the reported test results reflect actual test execution. AI assistance supported the development and verification process, while the final code, functionality, and test results were reviewed as part of the project workflow.
