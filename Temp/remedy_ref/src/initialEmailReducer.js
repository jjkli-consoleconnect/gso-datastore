const { cleanEmailContent } = require("./emailReducer");

/**
 * Extracts the most recent message from a long email thread string.
 * It works by finding the first quoted reply header (e.g., "On ... wrote:")
 * and returning everything before it.
 *
 * @param {string} fullEmailText - The entire raw text content of the email.
 * @returns {string} The cleaned, initial message text.
 */
function getInitialMessage(fullEmailText) {
  // Step 1: Find the start of the actual message body.
  const bodyStartIndex = fullEmailText.indexOf('--- \r\n');
  const emailBody = bodyStartIndex !== -1 
    ? fullEmailText.substring(bodyStartIndex + '--- \r\n'.length) 
    : fullEmailText;

  // Step 2: Define a regular expression to find the reply header.
  const replyHeaderRegex = /^On\s+.*?,?\s+\d{1,2}\s+\w+\s+\d{4}\s+at\s+\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?\s*.*?\s*wrote:$/im;

  // Step 3: Find the first match for this reply header in the email body.
  const match = replyHeaderRegex.exec(emailBody);

  let initialMessage;
  if (match) {
    // Step 4: If a match is found, the initial message is everything before it.
    initialMessage = emailBody.substring(0, match.index);
  } else {
    // Step 5: If no reply header is found, the entire body is the initial message.
    initialMessage = emailBody;
  }
  // Step 6: Clean up trailing whitespace and newlines from the extracted message.
  return cleanEmailContent(initialMessage.trim());
}

module.exports = { getInitialMessage };