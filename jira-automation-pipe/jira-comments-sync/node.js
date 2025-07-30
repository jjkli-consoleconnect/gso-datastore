const { BigQuery } = require('@google-cloud/bigquery');
const bigquery = new BigQuery();

// Helper to normalize timestamps
function fixTimestamp(value) {
  if (!value || typeof value !== 'string') return null;
  const match = value.match(/^(.+T\d{2}:\d{2}:\d{2})(\.\d+)?([+-]\d{4})$/);
  if (!match) return new Date(value).toISOString();
  const [_, time, fraction = '.000', offset] = match;
  const formatted = `${time}${fraction}${offset.slice(0, 3)}:${offset.slice(3)}`;
  return new Date(formatted).toISOString();
}

// Helper to remove control characters from strings
function sanitizeString(str) {
  if (typeof str !== 'string') return str;
  // Remove all control characters except newline and tab
  return str.replace(/[\x00-\x09\x0B-\x1F\x7F]/g, '');
}

// Cloud Function entry point
exports.jiraCommentWebhook = async (req, res) => {
  console.log('📬 Comment webhook triggered');
  console.log('🔎 Raw body:', JSON.stringify(req.body, null, 2));

  try {
    const data = req.body;

    // Map/normalize fields as needed
    const row = {
      Issue_Key: data.Issue_Key,
      Comment_ID: data.Comment_ID,
      Author_Account_ID: data.Author_Account_ID,
      Author_Display_Name: data.Author_Display_Name,
      Created: fixTimestamp(data.Created),
      Updated: fixTimestamp(data.Updated),
      Body: sanitizeString(data.Body),
      Visibility_Type: data.Visibility_Type || null,
      Visibility_Value: data.Visibility_Value || null,
      SyncTime: new Date().toISOString()
    };

    console.log('📦 Final comment row:', JSON.stringify(row, null, 2));

    // Insert directly into the final BigQuery table
    await bigquery
      .dataset('GSO')
      .table('JiraComments')
      .insert([row]);

    console.log('✅ Comment insert successful');
    res.status(200).send('Comment inserted successfully');
  } catch (err) {
    console.error('❌ Comment insert failed:', JSON.stringify(err.errors || err, null, 2));
    res.status(500).send('Error during comment insert');
  }
};