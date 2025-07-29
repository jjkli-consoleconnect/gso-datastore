const { BigQuery } = require('@google-cloud/bigquery');
const { ulid } = require('ulid');               // npm install ulid 
const bigquery = new BigQuery();

/**
 * Generate a synthetic history ID if Jira didn’t supply one.
 * e.g. "GDA-24_01F8XYZ1234567890"
 */
function genHistoryId(issueKey) {
  return `${issueKey}_${ulid()}`;
}

function isEmpty(val) {
  return val === undefined || val === null || (typeof val === 'string' && val.trim() === '');
}

exports.jiraChangelogWebhook = async (req, res) => {
  // Only allow POST
  if (req.method !== 'POST') {
    return res.status(405).send('Method Not Allowed');
  }

  const d = req.body;
  
  // Basic payload validation
  if (!d.Issue_Key) {
    console.error('Missing Issue_Key in payload', d);
    return res.status(400).send('Bad Request: missing Issue_Key');
  }

  // Determine timestamp: use incoming or server-generated UTC ISO
  const now = new Date().toISOString();
  const transitionTs = isEmpty(d.Transition_Timestamp) ? now : d.Transition_Timestamp;

  // Determine History_ID: use incoming or generate one
  const historyId = isEmpty(d.History_ID) ? genHistoryId(d.Issue_Key) : d.History_ID;

  // Assemble your row; default empty string for any missing fields
  const row = {
    Issue_Key:                    d.Issue_Key,
    History_ID:                   historyId,
    Transition_Timestamp:         transitionTs,
    Transitioned_From:            d.Transitioned_From   || '',
    Transitioned_To:              d.Transitioned_To     || '',
    Transitioned_By_Account_ID:   d.Transitioned_By_Account_ID || '',
    Transitioned_By_Display_Name: d.Transitioned_By_Display_Name || '',
    SyncTime:                     now
  };

  try {
    await bigquery
      .dataset('GSO')
      .table('JiraChangelog')
      .insert(
        [row],
        {
          // Use our synthetic or incoming historyId as insertId for de-dup
          insertId: historyId
        }
      );

    console.log('✔︎ row inserted:', row);
    return res.status(200).send('OK');
  } catch (err) {
    console.error('❌ BigQuery insert failed', err);
    return res.status(500).send('Internal Server Error');
  }
};