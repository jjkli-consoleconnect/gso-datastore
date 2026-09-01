SELECT perf.*
FROM `pccw-internal-virt-agent-uat.GSO.VerificationPRRequesterPerformance` AS perf
JOIN `pccw-internal-virt-agent-uat.GSO.VerificationTeamNames` AS team
  ON perf.requester_name = team.FullNameRawData;
