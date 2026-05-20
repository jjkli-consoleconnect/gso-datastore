function cleanEmailContent(fullEmailText) {
  const regex = /On (Sun|Mon|Tue|Wed|Thu|Fri|Sat)/;
  const match = fullEmailText.match(regex);

  if (match) {
    return fullEmailText.substring(0, match.index).trim();
  } else {
    return fullEmailText.trim();
  }
}

module.exports = { cleanEmailContent };