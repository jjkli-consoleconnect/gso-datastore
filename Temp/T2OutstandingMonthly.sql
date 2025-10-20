/**
 * Google Apps Script: Tier-2 Outstanding Monthly Report
 * ------------------------------------------------------
 * 1. Enable the BigQuery Advanced Service (Services > BigQuery).
 * 2. Map this Apps Script project to a GCP project with BigQuery API enabled.
 * 3. Update the configuration constants below, save, then create a time-driven trigger
 *    calling `sendT2OutstandingMonthlyReport` on your desired schedule.
 */

const PROJECT_ID = 'pccw-internal-virt-agent-uat';
const RECIPIENTS = ['jens-vertexai-aaaan3dj2p4fdro72c3fa2l3km@consoleconnect.org.slack.com'];
const CC_RECIPIENTS = ['jjkli@consoleconnect.com'];
const REPORT_TITLE = 'Tier 2 Outstanding Report - Monthly';
const TIMEZONE = 'UTC';
const EMAIL_GREETING = 'Hi Team,';
const EMAIL_BODY_LINES = [
	EMAIL_GREETING,
	'',
	'Please see the attached Tier 2 Outstanding Monthly report.',
	'',
	'Kind regards,',
	'Data & Analytics Team'
];
const EMAIL_BODY_TEXT = EMAIL_BODY_LINES.join('\n');

const SQL_QUERY = `
SELECT DISTINCT
	Key,
	JiraStatus AS Status,
  SecondTierAssignee AS Assignee,
	Summary,
  ProductFamily,
	Type AS IssueType,
	Created,
	Updated,
	Resolved,
	ARRAY_TO_STRING(RemedyTicketNumber, ', ') AS RemedyTicketNumber,
	Links,
	ProjectCode,
	ROUND(
		TIMESTAMP_DIFF(TIMESTAMP(CURRENT_DATETIME(@timezone)), Created, SECOND) / 3600.0,
		2
	) AS TicketDurationHours
FROM
	\`pccw-internal-virt-agent-uat.GSO.JIRA_HD\`
WHERE
    ProjectCode IN ('CCAS', 'TAC', 'VOICECE', 'IOTCE', 'TXCE', 'SMSCE')
	  AND JiraStatus NOT IN ('Resolved', 'Closed', 'Cancelled', 'Done', 'Denied', 'Completed', 'Cancellation', 'One Time Commissioned', 'Operation', 'Closed / Resolved')
ORDER BY
	TicketDurationHours DESC;`;

/**
 * Entry point: executes the BigQuery job, formats results, and emails the report.
 */
function sendT2OutstandingMonthlyReport() {
	const data = runQuery(SQL_QUERY, { timezone: TIMEZONE });

	if (!data.rows.length) {
		GmailApp.sendEmail(joinAddresses(RECIPIENTS), REPORT_TITLE, 'No outstanding Tier-2 tickets found for this period.', {
			cc: joinAddresses(CC_RECIPIENTS)
		});
		return;
	}

	const csvContent = buildCsv(data.headers, data.rows);

	GmailApp.sendEmail(joinAddresses(RECIPIENTS), REPORT_TITLE, EMAIL_BODY_TEXT, {
		cc: joinAddresses(CC_RECIPIENTS),
		htmlBody: buildHtmlBody(),
		attachments: [
			{
				fileName: `${sanitiseFileName(REPORT_TITLE)}.csv`,
				content: csvContent,
				mimeType: 'text/csv'
			}
		]
	});
}

/**
 * Executes a parameterised BigQuery query and returns headers + rows (2D array of strings).
 */
function runQuery(sql, params) {
	const job = BigQuery.Jobs.insert(
		{
			configuration: {
				query: {
					query: sql,
					useLegacySql: false,
					parameterMode: 'NAMED',
					queryParameters: Object.entries(params || {}).map(([name, value]) => ({
						name,
						parameterType: { type: 'STRING' },
						parameterValue: { value }
					}))
				}
			}
		},
		PROJECT_ID
	);

	const jobId = job.jobReference.jobId;
	let queryResults;
	do {
		queryResults = BigQuery.Jobs.getQueryResults(PROJECT_ID, jobId, { timeoutMs: 1000 * 10 });
		if (!queryResults.jobComplete) Utilities.sleep(2000);
	} while (!queryResults.jobComplete);

	const headers = queryResults.schema.fields.map(field => field.name);
	const rows = (queryResults.rows || []).map(row => row.f.map(cell => formatCell(cell.v)));

	let pageToken = queryResults.pageToken;
	while (pageToken) {
		const page = BigQuery.Jobs.getQueryResults(PROJECT_ID, jobId, { pageToken });
		rows.push(
			...(page.rows || []).map(row => row.f.map(cell => formatCell(cell.v)))
		);
		pageToken = page.pageToken;
	}

	return { headers, rows };
}

function formatCell(value) {
	if (value === null || value === undefined) return '';
	if (Array.isArray(value)) return value.join(', ');
	if (typeof value === 'object' && value.value !== undefined) return formatCell(value.value);
	return `${value}`.replace(/\r?\n/g, ' ');
}

function buildCsv(headers, rows) {
	const esc = str => `"${str.replace(/"/g, '""')}"`;
	const csvRows = [headers.map(esc).join(',')];
	rows.forEach(row => csvRows.push(row.map(esc).join(',')));
	return csvRows.join('\n');
}

function buildHtmlBody() {
	return `
		<div style="font-family:Arial, sans-serif;font-size:13px;line-height:1.6;">
			<p>${EMAIL_GREETING}</p>
			<p>Please see the attached Tier 2 Outstanding Monthly report.</p>
			<p>Kind regards,<br>Data &amp; Analytics Team</p>
		</div>
	`;
}

function joinAddresses(addresses) {
	return (addresses || []).filter(Boolean).join(',');
}

function sanitiseFileName(name) {
	return name.replace(/[^a-z0-9\-_]+/gi, '_');
}
