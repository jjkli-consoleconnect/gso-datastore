/**
 * Training data verification - cross-checks Slack user email against BigQuery TrainingData table.
 * Users must have completed "AI DOs & DON'Ts" training (email in TrainingData) to access Wanda.
 */
const { BigQuery } = require('@google-cloud/bigquery');
const config = require('./config');

const bigquery = new BigQuery();

const TRAINING_REQUIRED_MESSAGE =
  'You need to complete the AI DO\'s & DON\'Ts training first before you can access Wanda. Please complete the training and try again. If you have completed the training and still received this message, please reach out to the team for assistance:\n' +
  '• Slack Channel: <#C06MT7WJF2Q>\n' +
  '• Email Address: <mailto:wanda@consoleconnect.com|Wanda Support>';

/**
 * Check if a user has completed training - first by email, then fallback to First_Name + Last_Name match.
 * @param {string} userEmail - The Slack user's email address
 * @param {string} [userName] - The Slack user's full name (real_name) for fallback match
 * @returns {Promise<{allowed: boolean, error?: string}>} - allowed: true if email or name found, false otherwise
 */
async function hasCompletedTraining(userEmail, userName) {
  const tableId = config.TRAINING_DATA_TABLE;

  if (!tableId) {
    console.warn('TRAINING_DATA_TABLE not set - skipping training verification (allowing access)');
    return { allowed: true };
  }

  const trimmedEmail = userEmail && typeof userEmail === 'string' ? userEmail.trim().toLowerCase() : '';
  const trimmedName = userName && typeof userName === 'string' ? userName.trim() : '';

  if (!trimmedEmail && !trimmedName) {
    console.warn('No valid email or name provided for training check');
    return { allowed: false };
  }

  // Validate table ID format (project.dataset.table - alphanumeric, dots, hyphens, underscores)
  if (!/^[a-zA-Z0-9._-]+$/.test(tableId)) {
    console.error('Invalid TRAINING_DATA_TABLE format');
    return { allowed: false, error: 'Invalid table configuration' };
  }

  try {
    // 1. Try exact email match first
    if (trimmedEmail) {
      const emailQuery = `
        SELECT 1
        FROM \`${tableId}\`
        WHERE LOWER(TRIM(Email_Address)) = @email
        LIMIT 1
      `;
      const [emailRows] = await bigquery.query({
        query: emailQuery,
        params: { email: trimmedEmail }
      });
      if (Array.isArray(emailRows) && emailRows.length > 0) {
        return { allowed: true };
      }

      // 2. Fallback: match only the local-part (before @), regardless of domain
      const localPart = trimmedEmail.split('@')[0] || '';
      if (localPart) {
        const localEmailQuery = `
          SELECT 1
          FROM \`${tableId}\`
          WHERE LOWER(TRIM(SPLIT(Email_Address, '@')[OFFSET(0)])) = @localPart
          LIMIT 1
        `;
        const [localRows] = await bigquery.query({
          query: localEmailQuery,
          params: { localPart }
        });
        if (Array.isArray(localRows) && localRows.length > 0) {
          return { allowed: true };
        }
      }
    }

    // 3. Fallback: match First_Name + ' ' + Last_Name against Slack username
    if (trimmedName) {
      const nameQuery = `
        SELECT 1
        FROM \`${tableId}\`
        WHERE LOWER(TRIM(CONCAT(COALESCE(First_Name,''), ' ', COALESCE(Last_Name,'')))) = LOWER(TRIM(@userName))
        LIMIT 1
      `;
      const [nameRows] = await bigquery.query({
        query: nameQuery,
        params: { userName: trimmedName }
      });
      if (Array.isArray(nameRows) && nameRows.length > 0) {
        return { allowed: true };
      }
    }

    return { allowed: false };
  } catch (error) {
    console.error('Training check BigQuery error:', error);
    return {
      allowed: false,
      error: error.message
    };
  }
}

module.exports = {
  hasCompletedTraining,
  TRAINING_REQUIRED_MESSAGE
};
