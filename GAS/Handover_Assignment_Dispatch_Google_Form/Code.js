function processMatchingEmails() {
  // --- Configurable Variables ---
  const subject = "Automated Report - Automated Handover Queue";
  const sender = "noreply-bmchelix@onbmc.com";
  const label = "pubsub";
  const formLink = "https://docs.google.com/forms/d/e/1FAIpQLScn2x63PItOvw0_GDRnZ2YApszYIi0gEeXRjtMDGg8QgR-gpQ/viewform";
  const recipientEmail = 'jens-vertexai-aaaan3dj2p4fdro72c3fa2l3km@consoleconnect.org.slack.com, jjkli@consoleconnect.com';
  const emailSubject = "Action Required: Handover Ticket Assignment";

  const query = `subject:${subject} from:${sender} label:${label} is:unread`;

  try {
    const threads = GmailApp.search(query);
    const numEmails = threads.length;

    if (numEmails > 0) {
      for (let i = 0; i < numEmails; i++) {
        const thread = threads[i];
        const message = thread.getMessages()[0];
        const emailSubjectActual = normalizeString(message.getSubject());
        const emailLabels = thread.getLabels().map(label => label.getName()).join(", ");

        // Check if the email subject matches exactly
        if (emailSubjectActual === normalizeString(subject)) {
          const messageId = message.getId();
          const formUrlWithId = formLink + "?messageId=" + messageId;

          MailApp.sendEmail({
            to: recipientEmail,
            subject: emailSubject,
            htmlBody: `Please select the team members who are on duty for the upcoming shift.<br><br><a href="${formUrlWithId}">Click here</a>` // Email body directly in sendEmail
          });

          thread.markRead();
        }
      }
    }
  } catch (error) {
    Logger.log(`Error processing emails: ${error}`);
  }
}

// Function to normalize a string by trimming and removing hidden characters
function normalizeString(str) {
  return str.replace(/\s+/g, ' ').trim();
}
