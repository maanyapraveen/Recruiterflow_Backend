-- Idempotent standalone SQLite setup and seed for Recruiter Bot.
-- Hand-written DDL. Idempotent, so it is safe to run on every startup.

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


BEGIN IMMEDIATE;
INSERT OR IGNORE INTO candidates (name, experience_years, availability, quirk) VALUES ('Sherlock H.', '8', 'Immediate', 'Solves problems by eliminating the impossible; occasionally insufferable in standups.');
INSERT OR IGNORE INTO candidates (name, experience_years, availability, quirk) VALUES ('Hermione G.', '4', '2 weeks', 'Reads the entire documentation before writing a single line of code.');
INSERT OR IGNORE INTO candidates (name, experience_years, availability, quirk) VALUES ('Tony S.', '12', 'Not looking', 'Ships an MVP overnight, refuses to write tests.');
INSERT OR IGNORE INTO candidates (name, experience_years, availability, quirk) VALUES ('Leslie K.', '6', 'Immediate', 'Has a binder for everything, including the binder.');
INSERT OR IGNORE INTO candidates (name, experience_years, availability, quirk) VALUES ('Ron S.', '15', 'Not looking', 'Refuses to use more than one monitor.');
INSERT OR IGNORE INTO candidates (name, experience_years, availability, quirk) VALUES ('Rick S.', '20', 'Immediate', 'Solution works, mechanism deeply concerning.');
INSERT OR IGNORE INTO candidates (name, experience_years, availability, quirk) VALUES ('Elle W.', '3', 'Immediate', 'Underestimated in every standup, correct in every retro.');
INSERT OR IGNORE INTO candidates (name, experience_years, availability, quirk) VALUES ('MacGyver', '10', '2 weeks', 'Fixes production outages with duct tape and a paperclip metaphor.');
INSERT OR IGNORE INTO candidates (name, experience_years, availability, quirk) VALUES ('Sheldon C.', '9', 'Immediate', 'Correct 95% of the time, insufferable 100% of the time.');
INSERT OR IGNORE INTO candidates (name, experience_years, availability, quirk) VALUES ('Katniss E.', '5', 'Immediate', 'Excellent under pressure, terrible with public speaking.');
INSERT OR IGNORE INTO candidates (name, experience_years, availability, quirk) VALUES ('Michael S.', '11', 'Not looking', 'World''s best boss, according to a mug he bought himself.');
INSERT OR IGNORE INTO candidates (name, experience_years, availability, quirk) VALUES ('Olivia P.', '13', '2 weeks', 'Handles it. Whatever it is.');
INSERT OR IGNORE INTO candidates (name, experience_years, availability, quirk) VALUES ('Ted L.', '7', 'Immediate', 'Turns every technical setback into a folksy metaphor.');
INSERT OR IGNORE INTO candidates (name, experience_years, availability, quirk) VALUES ('Miranda P.', '18', 'Not looking', 'Reviews every PR personally. Says nothing. Everyone panics.');
INSERT OR IGNORE INTO candidates (name, experience_years, availability, quirk) VALUES ('Dwight S.', '9', 'Immediate', 'Assistant to the regional backend engineer.');
INSERT OR IGNORE INTO jobs (title, min_experience_years, tagline) VALUES ('Backend Detective', '3', 'We have a bug. We have no leads. We have you.');
INSERT OR IGNORE INTO jobs (title, min_experience_years, tagline) VALUES ('Rapid Prototyping Engineer', '2', 'Ship first, document never (kidding - please document).');
INSERT OR IGNORE INTO jobs (title, min_experience_years, tagline) VALUES ('Developer Relations Lead', '2', 'Explain complex things to confused humans, cheerfully.');
INSERT OR IGNORE INTO jobs (title, min_experience_years, tagline) VALUES ('Engineering Manager, Chaos Team', '5', 'Herd cats. The cats are senior engineers.');
INSERT OR IGNORE INTO jobs (title, min_experience_years, tagline) VALUES ('Incident Commander', '4', '3am page. You''re the one who picks up.');
INSERT OR IGNORE INTO jobs (title, min_experience_years, tagline) VALUES ('Sales Engineer', '3', 'Sell the vision, then go build it.');
INSERT OR IGNORE INTO skills(name) VALUES ('chemistry');
INSERT OR IGNORE INTO skills(name) VALUES ('crisis-management');
INSERT OR IGNORE INTO skills(name) VALUES ('deduction');
INSERT OR IGNORE INTO skills(name) VALUES ('forensics');
INSERT OR IGNORE INTO skills(name) VALUES ('leadership');
INSERT OR IGNORE INTO skills(name) VALUES ('loyalty');
INSERT OR IGNORE INTO skills(name) VALUES ('mentorship');
INSERT OR IGNORE INTO skills(name) VALUES ('minimalism');
INSERT OR IGNORE INTO skills(name) VALUES ('negotiation');
INSERT OR IGNORE INTO skills(name) VALUES ('optimism');
INSERT OR IGNORE INTO skills(name) VALUES ('pattern-recognition');
INSERT OR IGNORE INTO skills(name) VALUES ('persuasion');
INSERT OR IGNORE INTO skills(name) VALUES ('precision');
INSERT OR IGNORE INTO skills(name) VALUES ('project-management');
INSERT OR IGNORE INTO skills(name) VALUES ('public-speaking');
INSERT OR IGNORE INTO skills(name) VALUES ('rapid-prototyping');
INSERT OR IGNORE INTO skills(name) VALUES ('research');
INSERT OR IGNORE INTO skills(name) VALUES ('resourcefulness');
INSERT OR IGNORE INTO skills(name) VALUES ('sales');
INSERT OR IGNORE INTO skills(name) VALUES ('security');
INSERT OR IGNORE INTO skills(name) VALUES ('stakeholder-management');
INSERT OR IGNORE INTO skills(name) VALUES ('strategy');
INSERT OR IGNORE INTO skills(name) VALUES ('systems-design');
INSERT OR IGNORE INTO skills(name) VALUES ('team-building');
INSERT OR IGNORE INTO skills(name) VALUES ('theoretical-analysis');
INSERT OR IGNORE INTO skills(name) VALUES ('time-management');
INSERT OR IGNORE INTO skills(name) VALUES ('woodworking');
INSERT OR IGNORE INTO tags(name) VALUES ('analytical');
INSERT OR IGNORE INTO tags(name) VALUES ('autonomous');
INSERT OR IGNORE INTO tags(name) VALUES ('blunt');
INSERT OR IGNORE INTO tags(name) VALUES ('brilliant');
INSERT OR IGNORE INTO tags(name) VALUES ('calm');
INSERT OR IGNORE INTO tags(name) VALUES ('calm-under-pressure');
INSERT OR IGNORE INTO tags(name) VALUES ('chaotic');
INSERT OR IGNORE INTO tags(name) VALUES ('confident');
INSERT OR IGNORE INTO tags(name) VALUES ('curious');
INSERT OR IGNORE INTO tags(name) VALUES ('decisive');
INSERT OR IGNORE INTO tags(name) VALUES ('demanding');
INSERT OR IGNORE INTO tags(name) VALUES ('detail-oriented');
INSERT OR IGNORE INTO tags(name) VALUES ('empathetic');
INSERT OR IGNORE INTO tags(name) VALUES ('energetic');
INSERT OR IGNORE INTO tags(name) VALUES ('enthusiastic');
INSERT OR IGNORE INTO tags(name) VALUES ('fast-paced');
INSERT OR IGNORE INTO tags(name) VALUES ('genius');
INSERT OR IGNORE INTO tags(name) VALUES ('improviser');
INSERT OR IGNORE INTO tags(name) VALUES ('innovative');
INSERT OR IGNORE INTO tags(name) VALUES ('intense');
INSERT OR IGNORE INTO tags(name) VALUES ('loyal');
INSERT OR IGNORE INTO tags(name) VALUES ('optimistic');
INSERT OR IGNORE INTO tags(name) VALUES ('organized');
INSERT OR IGNORE INTO tags(name) VALUES ('overachiever');
INSERT OR IGNORE INTO tags(name) VALUES ('persistent');
INSERT OR IGNORE INTO tags(name) VALUES ('principled');
INSERT OR IGNORE INTO tags(name) VALUES ('reckless');
INSERT OR IGNORE INTO tags(name) VALUES ('resilient');
INSERT OR IGNORE INTO tags(name) VALUES ('rigid');
INSERT OR IGNORE INTO tags(name) VALUES ('sharp');
INSERT OR IGNORE INTO tags(name) VALUES ('stubborn');
INSERT OR IGNORE INTO tags(name) VALUES ('tenacious');
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Sherlock H.' AND s.name = 'deduction';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Sherlock H.' AND s.name = 'pattern-recognition';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Sherlock H.' AND s.name = 'forensics';
INSERT OR IGNORE INTO candidate_traits(candidate_id, tag_id) SELECT c.id, t.id FROM candidates c, tags t WHERE c.name = 'Sherlock H.' AND t.name = 'analytical';
INSERT OR IGNORE INTO candidate_traits(candidate_id, tag_id) SELECT c.id, t.id FROM candidates c, tags t WHERE c.name = 'Sherlock H.' AND t.name = 'blunt';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Hermione G.' AND s.name = 'research';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Hermione G.' AND s.name = 'time-management';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Hermione G.' AND s.name = 'public-speaking';
INSERT OR IGNORE INTO candidate_traits(candidate_id, tag_id) SELECT c.id, t.id FROM candidates c, tags t WHERE c.name = 'Hermione G.' AND t.name = 'detail-oriented';
INSERT OR IGNORE INTO candidate_traits(candidate_id, tag_id) SELECT c.id, t.id FROM candidates c, tags t WHERE c.name = 'Hermione G.' AND t.name = 'overachiever';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Tony S.' AND s.name = 'systems-design';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Tony S.' AND s.name = 'rapid-prototyping';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Tony S.' AND s.name = 'leadership';
INSERT OR IGNORE INTO candidate_traits(candidate_id, tag_id) SELECT c.id, t.id FROM candidates c, tags t WHERE c.name = 'Tony S.' AND t.name = 'confident';
INSERT OR IGNORE INTO candidate_traits(candidate_id, tag_id) SELECT c.id, t.id FROM candidates c, tags t WHERE c.name = 'Tony S.' AND t.name = 'innovative';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Leslie K.' AND s.name = 'project-management';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Leslie K.' AND s.name = 'stakeholder-management';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Leslie K.' AND s.name = 'public-speaking';
INSERT OR IGNORE INTO candidate_traits(candidate_id, tag_id) SELECT c.id, t.id FROM candidates c, tags t WHERE c.name = 'Leslie K.' AND t.name = 'tenacious';
INSERT OR IGNORE INTO candidate_traits(candidate_id, tag_id) SELECT c.id, t.id FROM candidates c, tags t WHERE c.name = 'Leslie K.' AND t.name = 'organized';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Ron S.' AND s.name = 'woodworking';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Ron S.' AND s.name = 'minimalism';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Ron S.' AND s.name = 'negotiation';
INSERT OR IGNORE INTO candidate_traits(candidate_id, tag_id) SELECT c.id, t.id FROM candidates c, tags t WHERE c.name = 'Ron S.' AND t.name = 'stubborn';
INSERT OR IGNORE INTO candidate_traits(candidate_id, tag_id) SELECT c.id, t.id FROM candidates c, tags t WHERE c.name = 'Ron S.' AND t.name = 'principled';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Rick S.' AND s.name = 'systems-design';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Rick S.' AND s.name = 'rapid-prototyping';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Rick S.' AND s.name = 'chemistry';
INSERT OR IGNORE INTO candidate_traits(candidate_id, tag_id) SELECT c.id, t.id FROM candidates c, tags t WHERE c.name = 'Rick S.' AND t.name = 'genius';
INSERT OR IGNORE INTO candidate_traits(candidate_id, tag_id) SELECT c.id, t.id FROM candidates c, tags t WHERE c.name = 'Rick S.' AND t.name = 'reckless';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Elle W.' AND s.name = 'persuasion';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Elle W.' AND s.name = 'research';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Elle W.' AND s.name = 'public-speaking';
INSERT OR IGNORE INTO candidate_traits(candidate_id, tag_id) SELECT c.id, t.id FROM candidates c, tags t WHERE c.name = 'Elle W.' AND t.name = 'optimistic';
INSERT OR IGNORE INTO candidate_traits(candidate_id, tag_id) SELECT c.id, t.id FROM candidates c, tags t WHERE c.name = 'Elle W.' AND t.name = 'sharp';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'MacGyver' AND s.name = 'rapid-prototyping';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'MacGyver' AND s.name = 'resourcefulness';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'MacGyver' AND s.name = 'chemistry';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'MacGyver' AND s.name = 'systems-design';
INSERT OR IGNORE INTO candidate_traits(candidate_id, tag_id) SELECT c.id, t.id FROM candidates c, tags t WHERE c.name = 'MacGyver' AND t.name = 'calm';
INSERT OR IGNORE INTO candidate_traits(candidate_id, tag_id) SELECT c.id, t.id FROM candidates c, tags t WHERE c.name = 'MacGyver' AND t.name = 'improviser';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Sheldon C.' AND s.name = 'theoretical-analysis';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Sheldon C.' AND s.name = 'pattern-recognition';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Sheldon C.' AND s.name = 'research';
INSERT OR IGNORE INTO candidate_traits(candidate_id, tag_id) SELECT c.id, t.id FROM candidates c, tags t WHERE c.name = 'Sheldon C.' AND t.name = 'rigid';
INSERT OR IGNORE INTO candidate_traits(candidate_id, tag_id) SELECT c.id, t.id FROM candidates c, tags t WHERE c.name = 'Sheldon C.' AND t.name = 'brilliant';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Katniss E.' AND s.name = 'precision';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Katniss E.' AND s.name = 'strategy';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Katniss E.' AND s.name = 'crisis-management';
INSERT OR IGNORE INTO candidate_traits(candidate_id, tag_id) SELECT c.id, t.id FROM candidates c, tags t WHERE c.name = 'Katniss E.' AND t.name = 'resilient';
INSERT OR IGNORE INTO candidate_traits(candidate_id, tag_id) SELECT c.id, t.id FROM candidates c, tags t WHERE c.name = 'Katniss E.' AND t.name = 'decisive';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Michael S.' AND s.name = 'sales';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Michael S.' AND s.name = 'public-speaking';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Michael S.' AND s.name = 'team-building';
INSERT OR IGNORE INTO candidate_traits(candidate_id, tag_id) SELECT c.id, t.id FROM candidates c, tags t WHERE c.name = 'Michael S.' AND t.name = 'enthusiastic';
INSERT OR IGNORE INTO candidate_traits(candidate_id, tag_id) SELECT c.id, t.id FROM candidates c, tags t WHERE c.name = 'Michael S.' AND t.name = 'chaotic';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Olivia P.' AND s.name = 'crisis-management';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Olivia P.' AND s.name = 'negotiation';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Olivia P.' AND s.name = 'strategy';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Olivia P.' AND s.name = 'leadership';
INSERT OR IGNORE INTO candidate_traits(candidate_id, tag_id) SELECT c.id, t.id FROM candidates c, tags t WHERE c.name = 'Olivia P.' AND t.name = 'decisive';
INSERT OR IGNORE INTO candidate_traits(candidate_id, tag_id) SELECT c.id, t.id FROM candidates c, tags t WHERE c.name = 'Olivia P.' AND t.name = 'intense';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Ted L.' AND s.name = 'team-building';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Ted L.' AND s.name = 'optimism';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Ted L.' AND s.name = 'mentorship';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Ted L.' AND s.name = 'public-speaking';
INSERT OR IGNORE INTO candidate_traits(candidate_id, tag_id) SELECT c.id, t.id FROM candidates c, tags t WHERE c.name = 'Ted L.' AND t.name = 'empathetic';
INSERT OR IGNORE INTO candidate_traits(candidate_id, tag_id) SELECT c.id, t.id FROM candidates c, tags t WHERE c.name = 'Ted L.' AND t.name = 'persistent';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Miranda P.' AND s.name = 'leadership';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Miranda P.' AND s.name = 'negotiation';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Miranda P.' AND s.name = 'stakeholder-management';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Miranda P.' AND s.name = 'precision';
INSERT OR IGNORE INTO candidate_traits(candidate_id, tag_id) SELECT c.id, t.id FROM candidates c, tags t WHERE c.name = 'Miranda P.' AND t.name = 'demanding';
INSERT OR IGNORE INTO candidate_traits(candidate_id, tag_id) SELECT c.id, t.id FROM candidates c, tags t WHERE c.name = 'Miranda P.' AND t.name = 'decisive';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Dwight S.' AND s.name = 'sales';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Dwight S.' AND s.name = 'negotiation';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Dwight S.' AND s.name = 'security';
INSERT OR IGNORE INTO candidate_skills(candidate_id, skill_id) SELECT c.id, s.id FROM candidates c, skills s WHERE c.name = 'Dwight S.' AND s.name = 'loyalty';
INSERT OR IGNORE INTO candidate_traits(candidate_id, tag_id) SELECT c.id, t.id FROM candidates c, tags t WHERE c.name = 'Dwight S.' AND t.name = 'intense';
INSERT OR IGNORE INTO candidate_traits(candidate_id, tag_id) SELECT c.id, t.id FROM candidates c, tags t WHERE c.name = 'Dwight S.' AND t.name = 'loyal';
INSERT OR IGNORE INTO job_skills(job_id, skill_id) SELECT j.id, s.id FROM jobs j, skills s WHERE j.title = 'Backend Detective' AND s.name = 'deduction';
INSERT OR IGNORE INTO job_skills(job_id, skill_id) SELECT j.id, s.id FROM jobs j, skills s WHERE j.title = 'Backend Detective' AND s.name = 'pattern-recognition';
INSERT OR IGNORE INTO job_skills(job_id, skill_id) SELECT j.id, s.id FROM jobs j, skills s WHERE j.title = 'Backend Detective' AND s.name = 'forensics';
INSERT OR IGNORE INTO job_culture_keywords(job_id, tag_id) SELECT j.id, t.id FROM jobs j, tags t WHERE j.title = 'Backend Detective' AND t.name = 'analytical';
INSERT OR IGNORE INTO job_culture_keywords(job_id, tag_id) SELECT j.id, t.id FROM jobs j, tags t WHERE j.title = 'Backend Detective' AND t.name = 'autonomous';
INSERT OR IGNORE INTO job_skills(job_id, skill_id) SELECT j.id, s.id FROM jobs j, skills s WHERE j.title = 'Rapid Prototyping Engineer' AND s.name = 'rapid-prototyping';
INSERT OR IGNORE INTO job_skills(job_id, skill_id) SELECT j.id, s.id FROM jobs j, skills s WHERE j.title = 'Rapid Prototyping Engineer' AND s.name = 'systems-design';
INSERT OR IGNORE INTO job_culture_keywords(job_id, tag_id) SELECT j.id, t.id FROM jobs j, tags t WHERE j.title = 'Rapid Prototyping Engineer' AND t.name = 'innovative';
INSERT OR IGNORE INTO job_culture_keywords(job_id, tag_id) SELECT j.id, t.id FROM jobs j, tags t WHERE j.title = 'Rapid Prototyping Engineer' AND t.name = 'fast-paced';
INSERT OR IGNORE INTO job_skills(job_id, skill_id) SELECT j.id, s.id FROM jobs j, skills s WHERE j.title = 'Developer Relations Lead' AND s.name = 'public-speaking';
INSERT OR IGNORE INTO job_skills(job_id, skill_id) SELECT j.id, s.id FROM jobs j, skills s WHERE j.title = 'Developer Relations Lead' AND s.name = 'research';
INSERT OR IGNORE INTO job_culture_keywords(job_id, tag_id) SELECT j.id, t.id FROM jobs j, tags t WHERE j.title = 'Developer Relations Lead' AND t.name = 'energetic';
INSERT OR IGNORE INTO job_culture_keywords(job_id, tag_id) SELECT j.id, t.id FROM jobs j, tags t WHERE j.title = 'Developer Relations Lead' AND t.name = 'curious';
INSERT OR IGNORE INTO job_skills(job_id, skill_id) SELECT j.id, s.id FROM jobs j, skills s WHERE j.title = 'Engineering Manager, Chaos Team' AND s.name = 'team-building';
INSERT OR IGNORE INTO job_skills(job_id, skill_id) SELECT j.id, s.id FROM jobs j, skills s WHERE j.title = 'Engineering Manager, Chaos Team' AND s.name = 'stakeholder-management';
INSERT OR IGNORE INTO job_skills(job_id, skill_id) SELECT j.id, s.id FROM jobs j, skills s WHERE j.title = 'Engineering Manager, Chaos Team' AND s.name = 'leadership';
INSERT OR IGNORE INTO job_culture_keywords(job_id, tag_id) SELECT j.id, t.id FROM jobs j, tags t WHERE j.title = 'Engineering Manager, Chaos Team' AND t.name = 'empathetic';
INSERT OR IGNORE INTO job_culture_keywords(job_id, tag_id) SELECT j.id, t.id FROM jobs j, tags t WHERE j.title = 'Engineering Manager, Chaos Team' AND t.name = 'organized';
INSERT OR IGNORE INTO job_skills(job_id, skill_id) SELECT j.id, s.id FROM jobs j, skills s WHERE j.title = 'Incident Commander' AND s.name = 'crisis-management';
INSERT OR IGNORE INTO job_skills(job_id, skill_id) SELECT j.id, s.id FROM jobs j, skills s WHERE j.title = 'Incident Commander' AND s.name = 'strategy';
INSERT OR IGNORE INTO job_skills(job_id, skill_id) SELECT j.id, s.id FROM jobs j, skills s WHERE j.title = 'Incident Commander' AND s.name = 'negotiation';
INSERT OR IGNORE INTO job_culture_keywords(job_id, tag_id) SELECT j.id, t.id FROM jobs j, tags t WHERE j.title = 'Incident Commander' AND t.name = 'decisive';
INSERT OR IGNORE INTO job_culture_keywords(job_id, tag_id) SELECT j.id, t.id FROM jobs j, tags t WHERE j.title = 'Incident Commander' AND t.name = 'calm-under-pressure';
INSERT OR IGNORE INTO job_skills(job_id, skill_id) SELECT j.id, s.id FROM jobs j, skills s WHERE j.title = 'Sales Engineer' AND s.name = 'sales';
INSERT OR IGNORE INTO job_skills(job_id, skill_id) SELECT j.id, s.id FROM jobs j, skills s WHERE j.title = 'Sales Engineer' AND s.name = 'public-speaking';
INSERT OR IGNORE INTO job_skills(job_id, skill_id) SELECT j.id, s.id FROM jobs j, skills s WHERE j.title = 'Sales Engineer' AND s.name = 'negotiation';
INSERT OR IGNORE INTO job_culture_keywords(job_id, tag_id) SELECT j.id, t.id FROM jobs j, tags t WHERE j.title = 'Sales Engineer' AND t.name = 'enthusiastic';
INSERT OR IGNORE INTO job_culture_keywords(job_id, tag_id) SELECT j.id, t.id FROM jobs j, tags t WHERE j.title = 'Sales Engineer' AND t.name = 'persistent';
COMMIT;
