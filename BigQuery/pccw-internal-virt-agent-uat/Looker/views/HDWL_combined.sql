SELECT 
  wl.*,
  hd.*
FROM `pccw-internal-virt-agent-uat.Looker.WorkLog` AS wl
FULL OUTER JOIN `pccw-internal-virt-agent-uat.Looker.helpdesk` AS hd
ON wl.IncidentNumber = hd.Incident_Number;

