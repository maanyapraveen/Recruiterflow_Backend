-- Question 1: 
SELECT jp.id AS job_posting_id, jp.title, r.name AS recruiter_name
FROM job_postings AS jp
JOIN recruiters AS r ON r.id = jp.recruiter_id
WHERE jp.status = 'open'
ORDER BY jp.id;

-- Question 2: 
SELECT jp.id AS job_posting_id, jp.title,
       COUNT(DISTINCT i.applicant_id) AS final_stage_applicants
FROM job_postings AS jp
LEFT JOIN interviews AS i
  ON i.job_posting_id = jp.id AND i.stage = 'Final'
GROUP BY jp.id, jp.title
ORDER BY jp.id;

-- Question 3:
SELECT 
    LOWER(REPLACE(TRIM(applicants.email), ' ', '')) AS person_email,
    MIN(applicants.full_name)                       AS full_name,
    COUNT(DISTINCT interviews.job_posting_id)       AS postings_applied_to
FROM applicants
JOIN interviews ON interviews.applicant_id = applicants.id
GROUP BY LOWER(REPLACE(TRIM(applicants.email), ' ', ''))
HAVING COUNT(DISTINCT interviews.job_posting_id) > 1;

-- Question 4: 
SELECT 
    r.id AS recruiter_id, 
    r.name AS recruiter_name,
    COUNT(*) AS final_stage_interviews,
    SUM(CASE WHEN i.outcome = 'passed' THEN 1 ELSE 0 END) AS final_stage_passed,
    ROUND(
        1.0 * SUM(CASE WHEN i.outcome = 'passed' THEN 1 ELSE 0 END) / COUNT(*), 
        3
    ) AS final_stage_conversion_rate
FROM recruiters AS r
JOIN job_postings AS jp ON jp.recruiter_id = r.id
JOIN interviews AS i ON i.job_posting_id = jp.id
WHERE i.stage = 'Final'
GROUP BY r.id, r.name
HAVING COUNT(*) >= 3
ORDER BY final_stage_conversion_rate DESC, r.name;

-- Question 5 (bonus): 
-- Question 5 (Bonus)
-- Recruiter with the most successful placements (passed at Final stage) per department.
-- Uses RANK() so tied top recruiters in any department are all included.
WITH placements AS (
    SELECT
        jp.department,
        r.id   AS recruiter_id,
        r.name AS recruiter_name,
        COUNT(i.id) AS successful_placements
    FROM interviews i
    JOIN job_postings jp ON jp.id = i.job_posting_id
    JOIN recruiters  r  ON r.id  = jp.recruiter_id
    WHERE i.stage = 'Final' 
      AND i.outcome = 'passed'
    GROUP BY jp.department, r.id, r.name
),
ranked AS (
    SELECT
        department,
        recruiter_id,
        recruiter_name,
        successful_placements,
        RANK() OVER (
            PARTITION BY department 
            ORDER BY successful_placements DESC
        ) AS rnk
    FROM placements
)
SELECT 
    department, 
    recruiter_id,
    recruiter_name, 
    successful_placements
FROM ranked
WHERE rnk = 1
ORDER BY department;