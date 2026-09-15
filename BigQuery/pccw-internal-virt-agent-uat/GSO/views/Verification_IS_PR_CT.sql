SELECT
  COALESCE(v.reportdate, r.reportdate) AS reportdate,
  COALESCE(v.verifier_name, r.requester_name) AS person_name,

  -- Verifier metrics
  v.crs_verified,
  v.cr_amount_verified_usd,
  v.crs_awaiting_verification,
  v.cr_amount_awaiting_verification_usd,
  v.brs_verified,
  v.brs_processed,
  v.brs_awaiting_verification,
  v.brs_awaiting_processing,
  v.prs_verified,
  v.prs_processed,
  v.prs_awaiting_verification,
  v.prs_awaiting_processing,
  v.cts_verified,
  v.cts_processed,
  v.cts_awaiting_verification,
  v.cts_awaiting_processing,
  v.iss_awaiting_for_matching,
  v.iss_charge_matched,
  v.iss_awaiting_cn_verification,
  v.iss_cn_verified,

  -- Requester metrics
  r.requester_group,
  r.prs_submitted,
  r.pr_line_items_submitted,
  r.cis_received,
  r.cis_awaiting_receipt,
  r.cts_submitted,
  r.brs_created,
  r.prs_created
FROM `pccw-internal-virt-agent-uat.GSO.VerificationVerifierPerformance` AS v
FULL OUTER JOIN `pccw-internal-virt-agent-uat.GSO.VerificationPRRequesterPerformance` AS r
  ON v.reportdate = r.reportdate
 AND v.verifier_name = r.requester_name
WHERE COALESCE(v.verifier_name, r.requester_name) IN (
  'Ng, Carmen (Verification Team)',
  'Tong, Edmond, KW',
  'Kwok, SW, Gavin',
  'Lau, Shing Chung, Ivanson',
  'Leung, Judy, HL',
  'Lo, Kwun Wa Kelvin',
  'Lee, Lok Sze',
  'Yau, Ho Hsuan',
  'Chee, Winny Grace',
  'Leung, Christopher SL',
  'To, Lai Shan Lisa',
  'Lau, Olivia, SY',
  'Law, Alex',
  'Granado, Ana Lea',
  'Divina, Cristina',
  'Ho, Emily',
  'Yim, Emily, TH',
  'Rai, Mark Brian',
  'Pang, Patten Ting Pong',
  'Chan, Priscilla',
  'Yuen, Rebecca',
  'Lee, Roy, HY',
  'Ng, Sara'
)
ORDER BY reportdate, person_name;

