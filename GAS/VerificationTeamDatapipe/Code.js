// Requires BigQuery and Drive advanced services to be enabled for this project.
const FOLDER_ID = '12-dyzk1wJl4siGjkyD63-wuuZsM2oIPF';
const PROCESSED_PROPERTY_KEY = 'verification_report_processed_at';
const PROCESSED_CHECKSUM_PROPERTY_KEY = 'verification_report_processed_md5';
const LEGACY_MODIFIED_TIME_TOLERANCE_MS = 60000;

const REPORT_CONFIGS = [
	{
		label: 'Verifier Performance Report',
		filePattern: /^(?:IS|Verifier) Performance Report\s+(\d{6})/i,
		target: {
			projectId: 'pccw-internal-virt-agent-uat',
			datasetId: 'GSO',
			tableId: 'VerificationVerifierPerformance'
		},
		columns: [
			col('Verifier Name', 'verifier_name', 'STRING', 'REQUIRED'),
			col('CRs verified (#)', 'crs_verified', 'INT64'),
			col('CR amount verified (USD)', 'cr_amount_verified_usd', 'FLOAT64'),
			col('CRs awaiting verification (#)', 'crs_awaiting_verification', 'INT64'),
			col('CR amount awaiting verification (USD)', 'cr_amount_awaiting_verification_usd', 'FLOAT64'),
			col('BRs verified (#)', 'brs_verified', 'INT64'),
			col('BRs processed (#)', 'brs_processed', 'INT64'),
			col('BRs awaiting verification (#)', 'brs_awaiting_verification', 'INT64'),
			col('BRs awaiting processing (#)', 'brs_awaiting_processing', 'INT64'),
			col('PRs verified (#)', 'prs_verified', 'INT64'),
			col('PRs processed (#)', 'prs_processed', 'INT64'),
			col('PRs awaiting verification (#)', 'prs_awaiting_verification', 'INT64'),
			col('PRs awaiting processing (#)', 'prs_awaiting_processing', 'INT64'),
			col('CTs verified (#)', 'cts_verified', 'INT64'),
			col('CTs processed (#)', 'cts_processed', 'INT64'),
			col('CTs awaiting verification (#)', 'cts_awaiting_verification', 'INT64'),
			col('CTs awaiting processing (#)', 'cts_awaiting_processing', 'INT64'),
			col('ISs awaiting for matching (#)', 'iss_awaiting_for_matching', 'INT64'),
			col('ISs Charge matched (#)', 'iss_charge_matched', 'INT64'),
			col('ISs awaiting CN verification (#)', 'iss_awaiting_cn_verification', 'INT64'),
			col('ISs CN verified (#)', 'iss_cn_verified', 'INT64')
		]
	},
	{
		label: 'PR Requester Performance Report',
		filePattern: /^PR Requester Performance Report\s+(\d{6})/i,
		target: {
			projectId: 'pccw-internal-virt-agent-uat',
			datasetId: 'GSO',
			tableId: 'VerificationPRRequesterPerformance'
		},
		columns: [
			col('Requester Group', 'requester_group', 'STRING'),
			col('Requester Name', 'requester_name', 'STRING', 'REQUIRED'),
			col('PRs submitted (#)', 'prs_submitted', 'INT64'),
			col('PR line items submitted (#)', 'pr_line_items_submitted', 'INT64'),
			col('CIs received (#)', 'cis_received', 'INT64'),
			col('CIs awaiting receipt (#)', 'cis_awaiting_receipt', 'INT64'),
			col('CTs submitted', 'cts_submitted', 'INT64'),
			col('BRs created (#)', 'brs_created', 'INT64'),
			col('PRs created (#)', 'prs_created', 'INT64')
		]
	}
];

function processVerificationReports() {
	processVerificationReportsInternal(true);
}

function rebuildHistoricalVerificationReports() {
	processVerificationReportsInternal(true);
}

function processVerificationReportsInternal(rebuildLegacyFiles) {
	const query = `'${FOLDER_ID}' in parents and trashed = false`;
			let pageToken;
			do {
				const response = Drive.Files.list({
					q: query,
					pageToken,
					fields: 'nextPageToken, files(id,name,mimeType,modifiedTime,md5Checksum,properties)'
				});
				const files = response.files || [];
				files.forEach(fileMeta => {
					if (isFileAlreadyProcessed(fileMeta, rebuildLegacyFiles)) {
						console.log(`Skipping already processed file: ${fileMeta.name}`);
						return;
					}
					const file = DriveApp.getFileById(fileMeta.id);
					const config = matchReportConfig(file.getName());
					if (!config) {
						console.log(`Skipping file without matching config: ${file.getName()}`);
						return;
					}
					try {
						processReportFile(file, config);
						markFileProcessed(fileMeta.id, fileMeta.md5Checksum);
					} catch (error) {
						console.error(`Failed to process ${file.getName()}: ${error.message}`);
					}
				});
				pageToken = response.nextPageToken;
			} while (pageToken);
}

function processReportFile(file, config) {
	const reportDate = extractReportDate(config, file.getName());
	const csvString = getCsvContent(file);
	const rows = parseCsv(csvString);
	if (!rows.length) {
		console.log(`No data rows found in ${file.getName()}`);
		return;
	}
	const schema = buildSchema(config);
	ensureTargetTable(config.target, schema);
	const tempTableId = createTempTable(config.target, schema);
	try {
		const bigQueryRows = transformRows(rows, config, reportDate);
		insertRows(config.target.projectId, config.target.datasetId, tempTableId, bigQueryRows);
		replaceReportDateFromTemp(config.target, tempTableId, schema, reportDate);
			console.log(`Processed ${bigQueryRows.length} rows from ${file.getName()} into ${config.target.tableId}`);
	} finally {
		dropTempTable(config.target, tempTableId);
	}
}

function isFileAlreadyProcessed(fileMeta, rebuildLegacyFiles) {
	const properties = fileMeta.properties || {};
	const processedChecksum = properties[PROCESSED_CHECKSUM_PROPERTY_KEY];
	if (processedChecksum && fileMeta.md5Checksum) {
		return processedChecksum === fileMeta.md5Checksum;
	}
	if (rebuildLegacyFiles) {
		return false;
	}
	const processedAt = Date.parse(properties[PROCESSED_PROPERTY_KEY]);
	const modifiedAt = Date.parse(fileMeta.modifiedTime);
	return Number.isFinite(processedAt)
		&& Number.isFinite(modifiedAt)
		&& modifiedAt <= processedAt + LEGACY_MODIFIED_TIME_TOLERANCE_MS;
}

function markFileProcessed(fileId, checksum) {
	const patch = {
		properties: {}
	};
	patch.properties[PROCESSED_PROPERTY_KEY] = new Date().toISOString();
	if (checksum) {
		patch.properties[PROCESSED_CHECKSUM_PROPERTY_KEY] = checksum;
	}
	Drive.Files.update(patch, fileId, null, {
		supportsAllDrives: true,
		fields: 'id,properties'
	});
}

function getCsvContent(file) {
	const mime = file.getMimeType();
	if (mime === MimeType.CSV || mime === 'text/csv') {
		return stripBom(file.getBlob().getDataAsString());
	}
	if (mime === MimeType.GOOGLE_SHEETS) {
		return exportGoogleFileToCsv(file.getId());
	}
	const excelTypes = [
		MimeType.MICROSOFT_EXCEL,
		MimeType.MICROSOFT_EXCEL_LEGACY,
		'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
	];
	if (excelTypes.indexOf(mime) !== -1) {
		return exportExcelToCsv(file.getId());
	}
	throw new Error(`Unsupported mime type ${mime} for file ${file.getName()}`);
}

function exportExcelToCsv(fileId) {
	const resource = {
		title: `temp-${fileId}-${Date.now()}`,
		mimeType: MimeType.GOOGLE_SHEETS
	};
	const copy = Drive.Files.copy(resource, fileId, { convert: true });
	try {
		return exportGoogleFileToCsv(copy.id);
	} finally {
		Drive.Files.remove(copy.id);
	}
}

function exportGoogleFileToCsv(fileId) {
	const url = `https://www.googleapis.com/drive/v3/files/${fileId}/export?mimeType=text/csv`;
	const response = UrlFetchApp.fetch(url, {
		headers: {
			Authorization: `Bearer ${ScriptApp.getOAuthToken()}`
		},
		muteHttpExceptions: false
	});
	return stripBom(response.getContentText());
}

function parseCsv(csvString) {
	const rows = Utilities.parseCsv(csvString);
	return rows.filter(row => row.join('').trim() !== '');
}

function transformRows(rows, config, reportDate) {
	const [header, ...dataRows] = rows;
	const headerMap = buildHeaderMap(header, config.columns);
	const requiredAliases = config.columns.filter(colDef => colDef.mode === 'REQUIRED').map(colDef => colDef.alias);
	const outputRows = [];
	dataRows.forEach((row, rowIndex) => {
		if (row.every(cell => !cell || cell.trim() === '')) {
			return;
		}
		const record = { reportdate: reportDate };
		header.forEach((_, columnIndex) => {
			const mapping = headerMap[columnIndex];
			if (!mapping) {
				return;
			}
			const rawValue = columnIndex < row.length ? String(row[columnIndex]).trim() : '';
			const typedValue = castValue(rawValue, mapping.type);
			record[mapping.alias] = typedValue;
		});
		requiredAliases.forEach(alias => {
			if (record[alias] === undefined || record[alias] === null || record[alias] === '') {
				throw new Error(`Required column ${alias} missing on row ${rowIndex + 2}`);
			}
		});
		outputRows.push(record);
	});
	return outputRows;
}

function castValue(rawValue, type) {
	if (rawValue === '') {
		return null;
	}
	const cleaned = rawValue.replace(/,/g, '');
	if (type === 'INT64') {
		const intValue = Number(cleaned);
		if (Number.isNaN(intValue)) {
			throw new Error(`Unable to parse integer from value "${rawValue}"`);
		}
		return intValue;
	}
	if (type === 'FLOAT64') {
		const floatValue = parseFloat(cleaned);
		if (Number.isNaN(floatValue)) {
			throw new Error(`Unable to parse float from value "${rawValue}"`);
		}
		return floatValue;
	}
	return rawValue;
}

function ensureTargetTable(target, schema) {
	try {
		BigQuery.Tables.get(target.projectId, target.datasetId, target.tableId);
	} catch (error) {
		const message = error && error.message ? error.message : '';
		const lowerMessage = message.toLowerCase();
		if (lowerMessage.indexOf('not found') === -1) {
			throw error;
		}
		const tableResource = {
			tableReference: {
				projectId: target.projectId,
				datasetId: target.datasetId,
				tableId: target.tableId
			},
			schema: {
				fields: schema
			}
		};
		BigQuery.Tables.insert(tableResource, target.projectId, target.datasetId);
	}
}

function createTempTable(target, schema) {
	const tempTableId = `${target.tableId}_tmp_${Date.now()}`;
	const tableResource = {
		tableReference: {
			projectId: target.projectId,
			datasetId: target.datasetId,
			tableId: tempTableId
		},
		schema: {
			fields: schema
		}
	};
	BigQuery.Tables.insert(tableResource, target.projectId, target.datasetId);
	return tempTableId;
}

function dropTempTable(target, tempTableId) {
	try {
		BigQuery.Tables.remove(target.projectId, target.datasetId, tempTableId);
	} catch (error) {
		console.warn(`Failed to drop temp table ${tempTableId}: ${error.message}`);
	}
}

function insertRows(projectId, datasetId, tableId, rows) {
	const batchSize = 500;
	for (let offset = 0; offset < rows.length; offset += batchSize) {
		const chunk = rows.slice(offset, offset + batchSize);
		const request = {
			rows: chunk.map((row, index) => ({
				insertId: `${tableId}-${offset + index}`,
				json: row
			}))
		};
		const response = BigQuery.Tabledata.insertAll(request, projectId, datasetId, tableId);
		if (response.insertErrors && response.insertErrors.length) {
			const messages = response.insertErrors.map(error => JSON.stringify(error)).join('; ');
			throw new Error(`BigQuery insert errors: ${messages}`);
		}
	}
}

function replaceReportDateFromTemp(target, tempTableId, schema, reportDate) {
	const targetTable = `\`${target.projectId}.${target.datasetId}.${target.tableId}\``;
	const tempTable = `\`${target.projectId}.${target.datasetId}.${tempTableId}\``;
	const insertColumns = schema.map(field => field.name);
	const replaceStatement = [
		'BEGIN TRANSACTION;',
		`DELETE FROM ${targetTable} WHERE reportdate = DATE '${reportDate}';`,
		`INSERT INTO ${targetTable} (${insertColumns.map(col => `\`${col}\``).join(', ')})`,
		`SELECT ${insertColumns.map(col => `\`${col}\``).join(', ')} FROM ${tempTable};`,
		'COMMIT TRANSACTION;'
	].join('\n');
	const job = {
		configuration: {
			query: {
				query: replaceStatement,
					useLegacySql: false,
					location: getDatasetLocation(target)
			}
		}
	};
		const insertedJob = BigQuery.Jobs.insert(job, target.projectId);
		waitForBigQueryJob(target.projectId, insertedJob.jobReference.jobId);
}

	function waitForBigQueryJob(projectId, jobId) {
		while (true) {
			const job = BigQuery.Jobs.get(projectId, jobId);
			const state = job.status.state;
			if (state === 'DONE') {
				if (job.status.errorResult) {
					throw new Error(`BigQuery job ${jobId} failed: ${JSON.stringify(job.status.errorResult)}`);
				}
				if (job.status.errors && job.status.errors.length) {
					throw new Error(`BigQuery job ${jobId} completed with errors: ${JSON.stringify(job.status.errors)}`);
				}
				return;
			}
			Utilities.sleep(2000);
		}
	}

	const DATASET_LOCATION_CACHE = {};

	function getDatasetLocation(target) {
		const cacheKey = `${target.projectId}:${target.datasetId}`;
		if (!DATASET_LOCATION_CACHE[cacheKey]) {
			const dataset = BigQuery.Datasets.get(target.projectId, target.datasetId);
			DATASET_LOCATION_CACHE[cacheKey] = dataset.location || 'US';
		}
		return DATASET_LOCATION_CACHE[cacheKey];
	}

function buildSchema(config) {
	const fields = [
		{
			name: 'reportdate',
			type: 'DATE',
			mode: 'REQUIRED'
		}
	];
	config.columns.forEach(column => {
		fields.push({
			name: column.alias,
			type: column.type,
			mode: column.mode || 'NULLABLE'
		});
	});
	return fields;
}

function buildHeaderMap(headerRow, columns) {
	const canonicalToColumn = {};
	columns.forEach(column => {
		canonicalToColumn[canonicalizeHeader(column.sourceHeader)] = column;
	});
	return headerRow.map(cell => canonicalToColumn[canonicalizeHeader(cell)] || null);
}

function canonicalizeHeader(value) {
	return value ? value.replace(/\s+/g, ' ').trim() : '';
}

function stripBom(text) {
	return text.replace(/^\uFEFF/, '');
}

function extractReportDate(config, fileName) {
	const baseName = fileName.replace(/\.[^./\\]+$/, '');
	const match = config.filePattern.exec(baseName);
	if (!match) {
		throw new Error(`Unable to extract report date from ${fileName}`);
	}
	const yyyymm = match[1];
	const year = yyyymm.substring(0, 4);
	const month = yyyymm.substring(4, 6);
	return `${year}-${month}-01`;
}

function matchReportConfig(fileName) {
	return REPORT_CONFIGS.find(config => config.filePattern.test(fileName.replace(/\.[^./\\]+$/, '')));
}

function col(sourceHeader, alias, type, mode) {
	return {
		sourceHeader,
		alias,
		type,
		mode: mode || 'NULLABLE'
	};
}
