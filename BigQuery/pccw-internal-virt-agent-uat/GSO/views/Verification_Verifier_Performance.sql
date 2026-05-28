SELECT ver.*
FROM `pccw-internal-virt-agent-uat.GSO.VerificationVerifierPerformance` AS ver
JOIN `pccw-internal-virt-agent-uat.GSO.VerificationTeamNames` AS team
  ON ver.verifier_name = team.FullNameRawData;
