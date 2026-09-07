SELECT
  COUNTIF(CAST(TrueMTTR_mins AS STRING) LIKE '%S%') AS contains_s,
  COUNTIF(CAST(TrueMTTR_mins AS STRING) LIKE '%SR%') AS contains_sr,
  COUNTIF(TrueMTTR_mins IS NOT NULL AND SRno IS NOT NULL AND CAST(TrueMTTR_mins AS STRING) = REGEXP_EXTRACT(SRno, r'[0-9]+')) AS mttr_equals_sr_digits,
  COUNTIF(TrueMTTR_mins IS NOT NULL AND SRno IS NOT NULL AND CAST(TrueMTTR_mins AS STRING) LIKE '%' || REGEXP_EXTRACT(SRno, r'[0-9]+') || '%') AS mttr_contains_sr_digits
FROM pccw-internal-virt-agent-uat.GSO.HelpDeskAllNOC