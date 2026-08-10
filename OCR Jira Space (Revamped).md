OCR Jira Space (Revamped)

Jira Admin Training Doc - New Space / Project Creation

https://consoleconnect.atlassian.net/wiki/x/kYAVeg

New Jira Space/Project Creation Request Template

ITEM

	

VALUE

	

EXPLANATION




Space Name

	

QMS Incidents, Corrective Action and Improvements Register

(QMS-ICAIR)

	

A short, clear title




Space Key

	

OCR

	

An abbreviation of the space name, the unique key used to identify the space (our admin will notify you if the key is used)

Recommended to align with the corresponding Confluence Space, if any.




Space Type

	

Service Space

	
Software Space (Jira Software): Designed for development teams, with features like backlogs, sprints, and boards (Scrum or Kanban) to track bugs, stories, and software releases. as well as features of Business Space
Business Space (Jira Work Management): For non-technical teams like Marketing, HR, or Finance. with simplified views like calendars, lists, and forms rather than development-heavy boards
Service Space (Jira Service Management): With additional core features on top of Software Space -
Customer Portal: Simplified, non-technical interface where "customers" (unlicensed users) can submit requests without seeing the complex backend
SLAs (Service Level Agreements): Includes built-in countdown timers and goals to ensure requests are resolved within a specific timeframe.
Queues: Specialized views that automatically group and prioritize tickets for "agents" (licensed users) to handle
It requires more complicated setup and configurations Guideline: When to Create a Jira Service Management Project



Work Item Types

	
Case Review
Corrective Action
	

Representations of the work items in your Jira Space (aka issues, or tickets)

Our admin would recommend reusing existing work types due to platform performance concerns.




Workflows

	

WORKFLOW STATUS:

CASE REVIEW WORKFLOW:
Open
In Progress
Closed
Cancelled
Pending External

CORRECTIVE ACTION WORKFLOW:
Open
In Progress
Verification (Verification of effectiveness after 90 days)
Closed
Cancelled

 

	

To start simple, a basic 3-step process: To Do → In Progress → Done

Or, specify existing workflows from other Jira space to be copied.

 

Different workflows can be mapped to different work item types.

Our admin would recommend reusing existing status names due to platform performance concerns.

Additional requirements / customizations would be arranged after :

Transitions: Pretty names of status transitions to be shown

Conditions: eg. to restrict the "Approve" transition so only authorized managers can click it

Validators: eg. to ensure critical fields are filled before moving a request for approval

Post Functions: eg. to assign to a specific team lead when the status moves to "Triage"

Transition Screens: eg. to pop up a specific screen only to input Reason for Declining




Screens

	

Create ticket - QMS-ICAIR Space

WORK TYPE - CASE REVIEW or CA

CASE REVIEW SCREEN: OCR#
Name (Reporter)
Email Address
Department/Team
Customer request for Formal (External) Root Cause Analysis Report 
Yes
No, only an internal root cause analysis is required at this time
Case Review Request Type (dropdown)
Service Delivery (Provisioning related)
Prolonged Incident (Fault, Problem Resolution)
Repeat Incident, Potentially Chronic Issue (Including repeated unknown outage causes)
Customer Feedback, Customer Satisfaction Survey
Planned Maintenance Issue (Failure to notify, incomplete maintenance, or unexpected impact)
Proactive monitoring and alert failure (missed or delayed alert, monitoring gap, or detection failure)
Platform onboarding issue
Termination in error
Date of Incident or Concern
Customer Name
Service Number (USN, SR#, Circuit ID, etc.)
Ticket Reference Number/s (Remedy, Jira, GSDT, IPCE, etc)
Summary of the Issue
Impact or Risk of the incident (check box):
Customer dissatisfaction
Financial loss
Legal or regulatory breach
Loss of customer confidence
Operational disruption
Reputational damage
SLA breach or rebate
Other

FOR QA ONLY FIELDS:

Reporter - staff who filed the OCR/ICAIR

Assignee - staff who is assigned to identify RCA/CA, explain and assess the ICAIR (from team involved with the issue)

Case Owner (or QA Owner) - QA assigned to manage the OCR

Priority (Reference Remedy - Critical, High, Medium, Low)
Incident Category (Operations, Delivery, Termination, Change Management, Feature Request, Onboarding, Survey, Reporting)
Start date - date when QA starts reviewing the ticket
Aging
End date - closure date of OCR (with RCA and CA)
Product Family (refer to Insight)
Concerned Team - Assignee team
Status - as per workflow
Root Cause Category (put options)
CA reference number
No CA - justification (Engineering quick fixes, Vendor led engineering quick fix CA, Issues resolved through established internal operational procedure, Force Majeure event, Others -comment reason, Others-move to improvement)

CORRECTIVE ACTION SCREEN -
CA#
CA date
CA raised by
QA Owner
Criticality of CA (High, Medium, Low)
Reference ICAIR Incident #/OCR #
Corrective Action
CA Category (Process Control Documentation, Tools or System, Training, Vendor improvement, Network enhancement, Record/Database update, Audit, Customized Process, Process Reinforcement)
Department or team involved
CA Assigned to/Responsible
CA Implementation date
Status (In Progress, Verification, Closed, Cancelled, Parked)
CA verified by
CA implementation check date - Completed date
Verification of effectiveness date - Closed date
Effectiveness verified by
Verification remarks (Verified effective, Ineffective open new CA)

NOTES:

For OCR and CA # - if it can be separate numbering queue
If year can be included
Can aging of each ticket be included in the fields?
	

Start with a simple “Create Screen” to avoid overwhelming users.

Or, specify existing screens from other Jira space to be copied.

List the fields in the order they appear. Try to re-use existing fields (you may study other Jira spaces).

Different screens can be mapped to different work item types.




Priorities

	
Critical
High
Medium
Low

	

Default:

Pick the required priority labels, and pick the default




Special Permission

	

Others can only edit / write in the comments, not the initial screen information?

Confidential tickets - only visible to those given access or tagged (@)

	




Space Owner

	

Eleni Koutsopoulos

	

The owner is the primary person to approve changes to this space




Space Administrator (s)

	

Cheryl Pilao

Romel Lopez

	

The colleagues who can administer this space




Agent

	

David Jaffe

Marion Carreon

Myle Divina

Paul Lam

	

We will create the space in the Sandbox environment first. Once testing is complete, please submit a Deployment Request to promote it to Production. Reference the flowchart below.

Remarks
Exception to Jira space creation for typical ART/Agile teams (cloning without customizations), please contact John Siegrist / APMO.
Currently only “company-managed” (in Jira context) spaces are allowed, instead of “team-managed” (in Jira context) spaces.

Guideline: When to Create a Jira Service Management Project

https://consoleconnect.atlassian.net/wiki/x/R4hXR

Purpose

To ensure efficient use of Jira Service Management agent licences and avoid unnecessary creation of service management projects, this guideline outlines when a JSM project is appropriate and highlights its limitations

When a Jira Service Management Project Is Needed

You should consider creating a JSM project only if:

Customer-facing support is required, such as:
External or internal users submitting requests via a portal or email.
Requests need to be tracked, triaged, and resolved by a dedicated support team.
Workflow includes approvals or SLA tracking, especially for:
Incident, problem, or change management.
Regulatory or compliance-driven processes.
Service delivery requires structured queues, automation, and reporting, including:
Use of SLAs, escalation rules, and performance metrics.
Integration with a knowledge base for self-service.
Collaboration between agents and other internal teams is necessary, and roles like Collaborator or Stakeholder can be leveraged to avoid agent licence consumption.
Limitations and Considerations
Agent Licence Consumption: Each JSM project requires licensed agents to manage requests. Licences are limited and should be assigned only to users performing core service desk functions.
Restricted Access: JSM projects do not automatically grant access to all Jira users. Only users assigned appropriate roles (e.g. Customer, Collaborator, Stakeholder) can interact with the project based on their permissions.
Cost Implications: Creating unnecessary JSM projects can lead to over-licensing and increased costs. Projects should be consolidated where possible, and roles should be reviewed regularly.
Incompatibility of ScriptRunner Behaviours: This type of event-driven scripts does not work with JSM projects. As of June 2025, the vendor is still working on it:
https://ecosystem.atlassian.net/browse/FRGE-774

Recommended Alternatives

If the use case does not involve structured service delivery or customer support:

Consider using a Jira Software or Jira Core project for internal tracking and collaboration.
Use Collaborator roles for internal team members who need to view or comment on issues but do not require full agent capabilities.

Quick Comparison

 

	

Jira Service Management (JSM) Project

	

Jira (Software / Core) Project




Feature Differences

	

Self-service portal, SLAs, queues, report templates

	

Scrum / Kanban boards, sprint planning, roadmaps, release management




Best For

	

Managing incidents, customer support

	

development lifecycles, issues tracking and collaborating

Role Matrix: Capabilities and Licensing

Role

	

Key Responsibilities

	

Access/Features

	

JSM Licence Required

	

Notes




Agent

	

Handle and resolve requests, manage queues, update issues

	

Full access to queues, workflows, SLAs, reports, internal/external comments

	

Yes

	

Core licensed user for active service delivery




Customer

	

Submit and track own requests

	
Portal/email access only
Cannot access the project via the normal Jira interface
Can only create tickets via the Customer Portal — a simplified UI designed for request submission and tracking
Cannot view others' tickets in the project unless they are explicitly shared
By default, any Jira user without an agent or admin license will be assigned the Customer role
	

No

	

Unlimited and free; restricted to portal view




Collaborator

	

Provide internal input, assist agents

	

View issues, add internal comments, watch/vote, no transitions or edits

	

No

	

Cannot interact with customers or manage issues




Project Admin

	

Configure project, manage users and workflows

	

Full project config access, manage roles, SLAs, queues

	

Yes

	

Can perform all agent tasks




Stakeholder

	

Approve/reject requests

	

View and approve assigned requests

	

No

	

Primarily used for Incident-type issues; requires licence in Free/Standard plans

Access Request Process

If access to a JSM project is needed:

Submit a CSCM request.
Contact the project owner or administrator for role assignment and access review.

ICAIR REGISTER: https://docs.google.com/spreadsheets/d/1Rya4Z239j3ywby1Yo-6Xpm2i9mFD-_oJ3C-lExg6QXg/edit?usp=sharing

GFORM: https://docs.google.com/forms/d/e/1FAIpQLSe7zgSNw1tzMh3lAprkF9NAFB9PifaVhO-X4tpF813lZxSPYA/formResponse

QMS CENTRAL

https://consoleconnect.atlassian.net/wiki/spaces/QMS/overview
