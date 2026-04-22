SELECT 

T, `Key`, 
Summary, 
Status, 
Created, 
Updated, 
Resolved, 
Assignee, 
CASE WHEN RemedyTicketNumber = '' THEN NULL ELSE RemedyTicketNumber END AS RemedyTicketNumber, 
CASE WHEN Links = '' THEN NULL ELSE Links END AS Links

 FROM `pccw-internal-virt-agent-uat.JIRAProjects.SecondTier` 
