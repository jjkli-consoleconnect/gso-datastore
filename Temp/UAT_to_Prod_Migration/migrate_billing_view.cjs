const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const project = 'pccw-internal-virtual-agent';
const api = 'https://bigquery.googleapis.com/bigquery/v2/projects';
const target = `${api}/${project}/datasets/Dashboards/tables/billing`;
const source = `${api}/pccw-internal-virt-agent-uat/datasets/wanda_ds/tables/billing`;
const sql = fs.readFileSync(path.resolve(__dirname, '..', '..', project,
  'BigQuery', 'Dashboards', 'views', 'billing.sql'), 'utf8').trim();
const normalize = value => value.replace(/\r\n/g, '\n').trim();
async function request(url, body, optional = false) {
  const response = await fetch(url, {
    method: body ? 'POST' : 'GET',
    headers: { Authorization: `Bearer ${process.env.GCP_ACCESS_TOKEN}`, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined, signal: AbortSignal.timeout(120000),
  });
  const value = await response.json();
  if (optional && response.status === 404) return null;
  if (!response.ok) throw new Error(JSON.stringify(value.error));
  return value;
}
async function query(text) {
  let result = await request(`${api}/${project}/queries`, {
    query: text, useLegacySql: false, location: 'EU', maxResults: 1,
    maximumBytesBilled: '5000000000', labels: { datacloud: 'vscode' },
  });
  const deadline = Date.now() + 180000;
  while (!result.jobComplete) {
    assert.ok(Date.now() < deadline, `Read timed out: ${result.jobReference.jobId}`);
    await new Promise(resolve => setTimeout(resolve, 1000));
    result = await request(`${api}/${project}/queries/${result.jobReference.jobId}?location=EU&maxResults=1`);
  }
  if (result.errors?.length) throw new Error(JSON.stringify(result.errors));
  return result;
}
const shape = fields => fields.map(({ name, type, mode }) => ({ name, type, mode: mode || 'NULLABLE' }));
async function main() {
  assert.ok(process.env.GCP_ACCESS_TOKEN, 'GCP_ACCESS_TOKEN required');
  const original = await request(source);
  assert.equal(normalize(original.view.query), normalize(sql), 'Live source SQL differs');
  const dataset = await request(`${api}/${project}/datasets/Dashboards`);
  assert.equal(dataset.location, 'EU');
  const existing = await request(target, undefined, true);
  if (existing) assert.equal(normalize(existing.view?.query || ''), normalize(sql), 'Existing target differs; refusing overwrite');
  const preview = await query(`SELECT * FROM (\n${sql}\n) migration_check LIMIT 0`);
  assert.deepEqual(shape(preview.schema.fields), shape(original.schema.fields));
  assert.equal(preview.schema.fields.length, 13);
  if (!existing) await request(`${api}/${project}/datasets/Dashboards/tables`, {
    tableReference: { projectId: project, datasetId: 'Dashboards', tableId: 'billing' },
    view: { query: sql, useLegacySql: false }, labels: { datacloud: 'vscode' },
    description: 'Shared billing source for UAT and Prod; original project labels and cost calculations preserved.',
  });
  const persisted = await request(target);
  assert.equal(normalize(persisted.view.query), normalize(sql));
  assert.deepEqual(shape(persisted.schema.fields), shape(original.schema.fields));
  const read = await query(`SELECT 1 AS readable FROM \`${project}.Dashboards.billing\`
    WHERE usage_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY) LIMIT 1`);
  assert.equal((await request(source)).etag, original.etag, 'UAT changed during deployment');
  const result = { Target: persisted.id, Status: 'DefinitionAndReadVerified',
    FieldCount: 13, PreviewJob: preview.jobReference, ReadJob: read.jobReference,
    HasRecentRows: Number(read.totalRows) > 0, SourceUnchanged: true };
  fs.writeFileSync(path.join(process.argv[2], 'billing-migration-results.json'), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result, null, 2));
}
main().catch(error => { console.error(error.message); process.exitCode = 1; });
