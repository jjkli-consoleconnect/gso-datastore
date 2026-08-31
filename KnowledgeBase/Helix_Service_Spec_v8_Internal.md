

**Trouble Ticketing**  
**API Specification**

| Prepared by : | Reviewed by : | Approved by : |
| ----- | ----- | :---- |
|  |  |  |
| Name: Josephine Fung Title :	Product Owner Date: | Name:  Title :	 Date: | Name:  Title:  Date: |

Disclaimer:  
This publication has been prepared and written by PCCW Global and is copyright. Other than for the purpose of and subject to the conditions prescribed under the Copyright Act, no part of it may in any form or by any means (electronic, mechanical, microcopying, photocopying recording or otherwise) be reproduced, stored in a retrieval system or transmitted without prior permission. Product or company names are trademarks or registered trademarks of their respective holders.

	**Amendments**

| Issue | Date | Details of Amendments | By |
| :---: | :---: | ----- | :---: |
| 1 | 11-02-2020 | Initial Draft | Josephine Fung |
| 2 | 28-02-2020 | Update the Search multiple ticket API & add work log APIs | Josephine Fung |
| 3 | 09-04-2020 | Compliance with MEF and TMF standard | Josephine Fung |
| 4 | 02-11-2020 | CTI related fields update per Telefonica requirements & MSSL information | Josephine Fung |
| 5 | 23-02-2021 | Reported source only accept “API”, removed ticket category and ticket type from ticket creation API | Josephine Fung |
| 6 | 28-10-2022 | Update access method for Internal platform | Josephine Fung |
| 7 | 30-03-2026 | Update latest tyk information | Josephine Fung |
|  |  |  |  |
|  |  |  |  |
|  |  |  |  |
|  |  |  |  |
|  |  |  |  |
|  |  |  |  |
|  |  |  |  |
|  |  |  |  |
|  |  |  |  |
|  |  |  |  |
|  |  |  |  |
|  |  |  |  |
|  |  |  |  |
|  |  |  |  |
|  |  |  |  |
|  |  |  |  |

Filename: (IT-DOP-xx) Helix – Service spec vxx.doc	

**TABLE OF CONTENT**

[**1\.**	**Introduction	4**](#introduction)

[**2\.**	**Getting Started	4**](#getting-started)

[**2.1 How to get access to API	4**](#2.1-how-to-get-access-to-tyk)

[**2.2 Explore API Store	4**](#heading=h.nsd90pyqd2ic)

[**2.3 Read API documentations	5**](#heading=h.17dg0s98tlzw)

[**3\. Trouble Ticketing Model	6**](#3.-trouble-ticketing-model)

[**3.1 Trouble Ticket	6**](#3.1-trouble-ticket)

[**3.2 Error	7**](#3.2-error)

[**4\. API Operations	7**](#4.-api-operations)

[**4.1 Create trouble ticket	7**](#4.1-create-trouble-ticket)

[**4.2 Retrieve trouble ticket	9**](#4.2-retrieve-trouble-ticket)

[**4.3 List trouble tickets	9**](#4.3-list-trouble-tickets)

[**4.4 Patch trouble ticket	10**](#4.4-patch-trouble-ticket)

[**4.5 Delete trouble ticket	12**](#4.5-delete-trouble-ticket)

[**5\. Enumeration	13**](#5.-enumeration)

[**5.2 Item:	13**](#5.2-item:)

[**5.3 Priority:	13**](#5.3-priority:)

[**5.4 Trouble Ticket Status Types	13**](#5.4-trouble-ticket-status-types)

[**5.5 Fault caused	14**](#5.5-fault-caused)

[**5.6 Ticket type	14**](#5.6-ticket-type)

# 

1. ## **Introduction** {#introduction}

This document describes the basic information of the APIs provided in Trouble Ticketing Management for PCCWG Internal platform access. It also acts as a user guide for API consumers on how to call the APIs in your custom applications.  
The Trouble Ticketing Management is a REST interface that lets a third-party application to consume web services to retrieve trouble ticket, create trouble ticket, modify trouble ticket status, add trouble ticket work information etc.

The operation process and related technical specification of the Trouble Ticketing Management follows MEF & TM Forum standard, which is based on the following MEF & TM Forum documents:

* MEF 55 \- Lifecycle Service Orchestration (LSO Sonata Trouble Ticketing API Project)  
* TMF621 \- Trouble\_Ticket\_API\_REST\_Specification, release 19.0.1

2. ## **Getting Started** {#getting-started}

We were using WSO2 API gateway, and we had migrated to TYK in 2024\. Please refer to [https://wiki.pccwglobal.com/pages/viewpage.action?spaceKey=CorporateServices\&title=API+Gateway+Migration](https://wiki.pccwglobal.com/pages/viewpage.action?spaceKey=CorporateServices&title=API+Gateway+Migration)  for the migration detail.

# 2.1 How to get access to TYK {#2.1-how-to-get-access-to-tyk}

Calling Ticketing API via Internal TYK API gateway requires an Auth0 account.  To apply an Auth0 account, you may refer to the sample ticket: https://consoleconnect.atlassian.net/browse/CSCM-18391. Please state your system id (name) in the ticket.  You will get your client id and client secret token after an Auth0 account is created.

Jwt token:  
Jwt token is needed for all Ticketing API calls.  You can obtain a jwt token by using your client ID and client secret token. 

Request

| curl \-k \-L "https://auth.stage.consoleconnect.com/oauth/token" \-H "Content-Type: application/x-www-form-urlencoded" \-d "client\_id={your client id}" \-d "client\_secret={your client secret token}" \-d "grant\_type=client\_credentials" \-d "audience=api.stage.corp.consoleconnect.com" |
| :---- |

## **3\. Trouble Ticketing Model** {#3.-trouble-ticketing-model}

# 3.1 Trouble Ticket {#3.1-trouble-ticket}

| Parameter | Type | Description |
| :---- | :---- | :---- |
| creationDate | DateTime | The date on which the trouble ticket was created |
| lastUpdate | DateTime | The date and time that the trouble ticket was last updated |
| description | String | Description of the trouble or issue |
| externalId | String | Additional identifier coming from an external system |
| id | String | Unique identifier of the trouble ticket |
| name | String | Name of the trouble ticket, typically a short description provided by the user that create the ticket |
| priority | String | The priority of the trouble ticket and how quickly the issue should be resolved. Example: Critical, High, Medium, Low |
| status | String | The current status of the trouble ticket |
| ticketType | String | Represent a business type of the trouble ticket. Example: Incident |
| channel | Object | The channel that origin the trouble ticket |
|     @type | String | A type of channel. Example: Customer, Internal, Proactive, Supplier, Supplier Proactive |
|     name | String | Name of the channel.  Example: API |
| relatedParty | Array | A related party defines party or party role linked to a specific entity |
|     phone | String | Phone number of the related entity |
|     email | String | Email of the related entity |
|     name | String | Name of the related entity |
|     role | String | Role played by the related party.  Example: Contact, Assigned Group |
| notes | Array | Extra information of the ticket entity  |
|     id | String | Identifier of the note within its containing entity |
|     text | String | Text of the note |
|     date | DateTime | Date of the note |
|     author | String | Author of the note |
|     @type | String | Type of the note.  Example: worklog, faultsymptom, faultlocation, faultcause, faultreason, etc. |
|     attachment | Array | Attachment file size is limited to 10M and files count limited to 3\. |
|         content | String | The actual contents of the attachment object, if embedded, encoded as base64. |
|         name | String | File name |
|         size | String | File size |
|         href | String | URI for this attachment |
| relatedEntity | Array | Related entities of the trouble ticket, such as Service Profile information, Voice subscription information, etc. |
|     name | String | Name of related entity |
|     role | String | The role of entity |
|     @type | String | The target instance type of the related entity |
|     @referredType | String | Entity type |
| troubleTicketRelationship | Array | Relationship related to the trouble ticket |
|     name | String | Name of the relationship |
|     relationshipType | String | Type of the Trouble Ticket relationship |

# 

# 3.2 Error {#3.2-error}

| Parameter | Type | Description |
| :---- | :---- | :---- |
| error | Object | Error information |
|     code | String | Error code |
|     title | String | Error message |
| detail | String | The detail of the error message |

Following error codes are defined:

| Error Code | Message Text | Description |
| :---- | :---- | :---- |
| 001 | Internal Error | Generic error code handling any failure not described in this table  |
| 002 | Workflow, state transition is not valid  | An attempt was made to specify an invalid state transition  |
| 003 | Workflow, invalid operation for state  | An attempt has been made on a service order that is not allowed in the current workflow state  |
| 004 | Input validation error  | Validation failed for input parameters, e.g. missing mandatory fields, parameter type incorrect  |

## **4\. API Operations**  {#4.-api-operations}

All available trouble ticket APIs support synchronous model at this stage.  We will consider implementing asynchronous model unless performance issue.

# 4.1 Create trouble ticket {#4.1-create-trouble-ticket}

| Interface Name | Create a new trouble ticket |
| :---- | ----- |
| **Interface** | API Gateway |
| **Recipients** | Customers |
| **Transport** | REST over HTTPS |
| **Operation Name** | POST |
| **Description** | Use the /cs-helix-ticketing/internalHelix/troubleTicket to create an incident ticket.  |
| **URL Template** | /cs-helix-ticketing/internalHelix/troubleTicket |
| **Header** |  **Name Mandatory Value** Authorization Yes Bearer {Jwt token}  |
| **Input Data** (Parameters) |  **Name Type Mandatory Description Value** troubleTicket object Yes Payload  **The following tables provide the list of mandatory and non mandatory attributes when creating a TroubleTicket, including any possible rule conditions and applicable default values.  Mandatory Attributes Rule** troubleTicket.name troubleTicket.priority troubleTicket.ticketType Default value “Incident” notes.@type Value “faultsymptom” notes.id Note.id \= “Item” is mandatory to describe the fault symptom notes.text Refer to section 5.2 for the list of item values relatedEntity Service Profile on customer id and sr id are keys pair to the trouble ticket  **Non-Mandatory Attributes Rule** troubleTicket.description troubleTicket.creationDate If empty, default with current system date and time troubleTicket.externalId Customer system trouble ticket unique id troubleTicket.status If empty, default with “Acknowledged” relatedParty Only keep one contact person information of this trouble ticket, and it won’t impact to customer/site/circuit master contact information notes channel.name If empty, default with “API” channel.@type If empty, default with “Customer” relatedEntity Optional to other entity, such as Voice subscription information  |
| **Input Sample** | ![][image1] |
| **Output sample OK** | 200 Content-type: application/json Trouble ticket return successfully with first level attributes., refer to 3.1 |
| **Output Error** | Error occurred, refer to 3.2 |
| **Communication Pattern** | REST sync Request-Response |

# 4.2 Retrieve trouble ticket {#4.2-retrieve-trouble-ticket}

| Interface Name | Retrieve an existing trouble ticket by ID |
| :---- | ----- |
| **Interface** | API Gateway |
| **Recipients** | Customers |
| **Transport** | REST over HTTPS |
| **Operation Name** | GET |
| **Description** | Use the /cs-helix-ticketing/internalHelix/troubleTicket/ URL to retrieve an existing trouble ticket by id |
| **URL Template** | /cs-helix-ticketing/internalHelix/troubleTicket/{id} |
| **Header** |  **Name Mandatory Value** Authorization Yes Bearer {Jwt token}  |
| **Input Data** (Parameters) |  **Name Type Mandatory Description Value** id String Yes Unique identifier of the trouble ticket INC000001665950  |
| **Input Sample** | GET [https://api.stage.corp.consoleconnect.com/cs-helix-ticketing/internalHelix/troubleTicket/INC000006741016](https://api.stage.corp.consoleconnect.com/cs-helix-ticketing/internalHelix/troubleTicket/INC000006741016) Authorization: Bearer {Jwt toke} |
| **Output sample OK** | 200 Content-type: application/json Trouble ticket return successfully with all levels attributes, refer to 3.1 |
| **Output Error** | Error occurred, refer to 3.2 |
| **Communication Pattern** | REST sync Request-Response |

# 

# 4.3 List trouble tickets {#4.3-list-trouble-tickets}

| Interface Name | Retrieve existing trouble tickets with the applied filters |
| :---- | ----- |
| **Interface** | API Gateway |
| **Recipients** | Customers |
| **Transport** | REST over HTTPS |
| **Operation Name** | GET |
| **Description** | Use the /cs-helix-ticketing/internalHelix/troubleTicket? URL to retrieve an existing trouble ticket by filter keys |
| **URL Template** | /cs-helix-ticketing/internalHelix/troubleTicket?{filters} |
| **Header** |  **Name Mandatory Value** Authorization Yes Bearer {Jwt token}  |
| **Input Data** (Parameters) |  **Name Type Mandatory Description** relatedEntity customerId String Yes\* status String Yes\* relatedEntity.sr String No Not all first level trouble ticket attributes are enabled for selection. Note: relatedEntity.customerId and status are mandatory fields.  Status “IN PROGRESS” will be default if not given.   Status available values for filtering: ACKNOWLEDGED, IN PROGRESS, RESOLVED, CANCELLED  |
| **Input Sample** | GET  https://api.stage.corp.consoleconnect.com/cs-helix-ticketing/internalHelix/troubleTicket?mode=Detail\&relatedEntity.customerId=TELEF\&status=Acknowledged\&page=2\&limit=50Content-Type: application/json  Authorization: Bearer {Jwt toke} |
| **Output sample OK** | 200 Content-type: application/json Trouble ticket(s) return successfully with first level attributes, refer to 3.1 |
| **Output Error** | Error occurred, refer to 3.2 |
| **Communication Pattern** | REST sync Request-Response |

# 

# 4.4 Patch trouble ticket {#4.4-patch-trouble-ticket}

| Interface Name | Update an existing trouble ticket |
| :---- | ----- |
| **Interface** | API Gateway |
| **Recipients** | Customers |
| **Transport** | REST over HTTPS |
| **Operation Name** | PATCH |
| **Description** | Use the /cs-helix-ticketing/internalHelix/troubleTicket/ URL to update an existing trouble ticket by id |
| **URL Template** | /cs-helix-ticketing/internalHelix/troubleTicket/{id} |
| **Header** |  **Name Mandatory Value** Authorization Yes Bearer {Jwt token}  |
| **Input Data** (Parameters) |  **Name Type Mandatory Description Value** troubleTicket object Yes Payload The tables below provide the list of patchable and non patchable attributes, including constraint rules on their usage. Patchable Attributes  Rules description externalId name status Only allows re-open the trouble ticket from “RESOLVED” back to “IN PROGRESS” for status change through API.  Other status are controlled by PCCWG operation teams through frontend interface. relatedParty Only allows when role is “Contact”     phone     email     name notes Only allows adding new notes with/without attachments for @type is “worklog”  |
| **Input Sample** | ![][image2] |
| **Output sample OK** | 200 Content-type: application/json Trouble ticket(s) return successfully with first level attributes, refer to 3.1 |
| **Output Error** | Error occurred, refer to 3.2 |
| **Communication Pattern** | REST sync Request-Response |

# 

# 4.5 Delete trouble ticket {#4.5-delete-trouble-ticket}

| Interface Name | Cancel an existing trouble ticket (used to mark delete only, trouble ticket status will change to “Cancelled”) |
| :---- | ----- |
| **Interface** | API Gateway |
| **Recipients** | Customers |
| **Transport** | REST over HTTPS |
| **Operation Name** | DELETE |
| **Description** | Use the /cs-helix-ticketing/internalHelix/troubleTicket URL to update an existing trouble ticket by id |
| **URL Template** | /cs-helix-ticketing/internalHelix/troubleTicket/{id} |
| **Header** |  **Name Mandatory Value** Content-Type Yes application/json Authorization Yes Bearer {{token}} userKey Yes Encrypted Insight account  |
| **Input Data** (Parameters) |  **Name Type Mandatory Description Value** id String Yes  |
| **Input Sample** | DELETE [https://api.stage.corp.consoleconnect.com/cs-helix-ticketing/internalHelix/troubleTicket/INC000006239616](https://api.stage.corp.consoleconnect.com/cs-helix-ticketing/internalHelix/troubleTicket/INC000006239616)  Authorization: Bearer {Jwt token} |
| **Output sample OK** | 200 Content-type: application/json refer to 3.1 |
| **Output Error** | Error occurred, refer to 3.2 |
| **Communication Pattern** | REST sync Request-Response |

## **5\. Enumeration** {#5.-enumeration}

# 

# 

# 5.2 Item: {#5.2-item:}

![][image3]

# 5.3 Priority: {#5.3-priority:}

CRITICAL  
HIGH  
MEDIUM  
LOW

# 5.4 Trouble Ticket Status Types {#5.4-trouble-ticket-status-types}

ACKNOWLEDGED  
IN PROGRESS  
PENDING  
RESOLVED  
CLOSED  
CANCELLED  
REJECTED  
HELD

# 

# 5.5 Fault caused {#5.5-fault-caused}

![][image4]

# 5.6 Ticket type {#5.6-ticket-type}

	Incident

\~\~ End \~\~

[image1]: <data:image/png;base64,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>

[image2]: <data:image/png;base64,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>

[image3]: <data:image/png;base64,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>

[image4]: <data:image/png;base64,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>