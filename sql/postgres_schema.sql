-- PostgreSQL option; the included runnable importer uses SQLite to avoid setup requirements.
CREATE TABLE IF NOT EXISTS interviews (
    interview_id text PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS utterances (
    interview_id text REFERENCES interviews(interview_id),
    turn_index integer NOT NULL,
    role text NOT NULL,
    speaker_ids text NOT NULL,
    start_seconds numeric,
    end_seconds numeric,
    content text NOT NULL,
    PRIMARY KEY (interview_id,turn_index)
);
CREATE TABLE IF NOT EXISTS predictions (
    interview_id text PRIMARY KEY REFERENCES interviews(interview_id),
    age_bracket text,
    gender text CHECK (gender IN ('female','male','unknown')),
    interview_year integer CHECK (interview_year IN (1970,2005)),
    status text,
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    method text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS utterances_content_search ON utterances USING gin (to_tsvector('simple',content));
-- Broad French numeric-age candidate discovery: not automatically an interviewee's current age.
SELECT interview_id, turn_index, start_seconds, content,
       (regexp_match(content, 'j''ai[[:space:]]+([0-9]{1,3})[[:space:]]+ans', 'i'))[1] AS candidate_age
FROM utterances
WHERE role='interviewee'
  AND content ~* 'j''ai[[:space:]]+[0-9]{1,3}[[:space:]]+ans';
