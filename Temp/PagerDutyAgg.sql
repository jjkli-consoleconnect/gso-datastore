SELECT 
-- Core/Common fields
EntityType, 
EntityId, 
ParentId, 
Name, 
Summary, 
Status, 
HtmlUrl, 
CreatedAt, 
UpdatedAt, 

-- Incident fields
IncidentNumber, 
Urgency AS IncidentUrgency, 
Title AS IncidentTitle, 
Description AS IncidentDescription, 
EscalationPolicyId, 
LastStatusChangeAt, 
JSON_VALUE(LastStatusChangeBy, '$.summary') AS IncidentLastStatusChangeBy,

-- Service fields
ServiceStatus,
ServiceDescription,
AutoResolveTimeout AS ServiceAutoResolveTimeout, 
AcknowledgementTimeout AS ServiceAcknowledgementTimeout, 
ServiceTeamSummaries,
ServiceIntegrationSummaries,

-- User fields
Email AS UserEmail, 
AvatarUrl AS UserAvatarUrl, 
UserRole, 
TimeZone AS UserTimeZone, 
UserTeamSummaries,

-- Team fields
TeamDescription,
MemberSummaries,

-- Schedule fields
ScheduleTimeZone,
ScheduleLayerSummaries,
OverrideSummaries,
FinalSchedule,

-- Escalation Policy fields
NumLayers,
RepeatEnabled,
EscalationRuleSummaries,

-- On-Call fields
UserId AS OnCallUserId, 
ScheduleId AS OnCallScheduleId, 
OnCallStart, 
OnCallEnd, 
OnCallLevel,

-- Metadata
SyncTime

FROM `pccw-internal-virt-agent-uat.GSO.PagerDuty` 