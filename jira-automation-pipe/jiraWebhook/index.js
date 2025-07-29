const { BigQuery } = require('@google-cloud/bigquery');
const bigquery = new BigQuery();

function fixTimestamp(value) {
  if (!value || typeof value !== 'string') return null;

  const match = value.match(/^(.+T\d{2}:\d{2}:\d{2})(\.\d+)?([+-]\d{4})$/);
  if (!match) return new Date(value).toISOString();

  const [_, time, fraction = '.000', offset] = match;
  const formatted = `${time}${fraction}${offset.slice(0, 3)}:${offset.slice(3)}`;
  return new Date(formatted).toISOString();
}

exports.jiraWebhook = async (req, res) => {
  console.log('📬 Webhook triggered');
  console.log('🔎 Raw body:', JSON.stringify(req.body, null, 2));

  try {
    const data = req.body;

    if (data.Component && typeof data.Component === 'string') {
      const trimmed = data.Component.replace(/,+$/, '');
      data.Component = trimmed.length > 0 ? trimmed.split(',') : [];
    } else if (!Array.isArray(data.Component)) {
      data.Component = [];
    }

    data.SyncTime = new Date().toISOString();
    data.Created = fixTimestamp(data.Created);
    data.Updated = fixTimestamp(data.Updated);
    data.Resolved = fixTimestamp(data.Resolved);

    console.log('📦 Final row:', JSON.stringify(data, null, 2));

    // ✅ Step: Insert into staging table
    await bigquery
      .dataset('Staging')
      .table('JiraTicket')
      .insert([data]);

    console.log('✅ Insert successful (merge will be handled by scheduled query)');
    res.status(200).send('Inserted successfully');
  } catch (err) {
    console.error('❌ Insert failed:', JSON.stringify(err.errors || err, null, 2));
    res.status(500).send('Error during insert');
  }
};