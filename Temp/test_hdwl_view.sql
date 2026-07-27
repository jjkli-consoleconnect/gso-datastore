SELECT Incident_Number, AIFaultCause
FROM `pccw-internal-virt-agent-uat.GSO.HDWL`
WHERE AIFaultCause IS NOT NULL
LIMIT 5;