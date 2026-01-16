function processMatchingEmails() {
  // --- Configurable Variables ---
  const subject = "Automated Report - Automated Handover Queue";
  const sender = "noreply-bmchelix@onbmc.com";
  const label = "dashboard-autoreports";
  const formLink = "https://docs.google.com/forms/d/e/1FAIpQLScn2x63PItOvw0_GDRnZ2YApszYIi0gEeXRjtMDGg8QgR-gpQ/viewform";

  // Pub/Sub Configuration
  const projectId = "pccw-internal-virt-agent-uat";
  const topicName = "gmail-handover-reports";
  const serviceAccountKey = getServiceAccountKey();

  const query = `subject:${subject} from:${sender} label:${label} is:unread`;

  try {
    const threads = GmailApp.search(query);
    const numEmails = threads.length;

    if (numEmails > 0) {
      for (let i = 0; i < numEmails; i++) {
        const thread = threads[i];
        const message = thread.getMessages()[0];
        const emailSubjectActual = normalizeString(message.getSubject());

        // Check if the email subject matches exactly
        if (emailSubjectActual === normalizeString(subject)) {
          const messageId = message.getId();
          const messageBody = message.getPlainBody();
          
          // Prepare message for Pub/Sub
          const pubsubMessage = {
            messageId: messageId,
            subject: emailSubjectActual,
            from: message.getFrom(),
            timestamp: new Date().toISOString()
          };

          // Publish to Pub/Sub
          publishToPubSub(projectId, topicName, pubsubMessage, serviceAccountKey);
          
          // Mark as read
          thread.markRead();
          
          Logger.log(`Published message ${messageId} to Pub/Sub`);
        }
      }
    }
  } catch (error) {
    Logger.log(`Error processing emails: ${error}`);
  }
}

// Get service account key from Properties Store
function getServiceAccountKey() {
  const scriptProperties = PropertiesService.getScriptProperties();
  const keyJson = scriptProperties.getProperty("SERVICE_ACCOUNT_KEY");
  
  if (!keyJson) {
    throw new Error("SERVICE_ACCOUNT_KEY not found in Script Properties. Please add the handover-pubsub-key.json content.");
  }
  
  return JSON.parse(keyJson);
}

// Publish message to Pub/Sub
function publishToPubSub(projectId, topicName, message, serviceAccountKey) {
  const token = getAccessToken(serviceAccountKey);
  const topicPath = `projects/${projectId}/topics/${topicName}`;
  
  const url = `https://pubsub.googleapis.com/v1/${topicPath}:publish`;
  
  const payload = {
    messages: [
      {
        data: Utilities.base64Encode(JSON.stringify(message))
      }
    ]
  };

  const options = {
    method: "post",
    headers: {
      Authorization: `Bearer ${token}`
    },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  };

  const response = UrlFetchApp.fetch(url, options);
  const result = JSON.parse(response.getContentText());

  if (response.getResponseCode() !== 200) {
    throw new Error(`Failed to publish to Pub/Sub: ${response.getContentText()}`);
  }

  return result;
}

// Get OAuth token for service account
function getAccessToken(serviceAccountKey) {
  const header = {
    alg: "RS256",
    typ: "JWT"
  };

  const now = Math.floor(Date.now() / 1000);
  const expirationTime = now + 3600;

  const payload = {
    iss: serviceAccountKey.client_email,
    scope: "https://www.googleapis.com/auth/pubsub",
    aud: "https://oauth2.googleapis.com/token",
    exp: expirationTime,
    iat: now
  };

  const signature = Utilities.computeRsaSha256Signature(
    JSON.stringify(header) + "." + JSON.stringify(payload),
    serviceAccountKey.private_key
  );

  const jwt = Utilities.base64Encode(JSON.stringify(header)) + "." +
              Utilities.base64Encode(JSON.stringify(payload)) + "." +
              Utilities.base64Encode(signature);

  const tokenUrl = "https://oauth2.googleapis.com/token";
  const tokenPayload = {
    grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer",
    assertion: jwt
  };

  const options = {
    method: "post",
    payload: Object.keys(tokenPayload)
      .map(key => encodeURIComponent(key) + "=" + encodeURIComponent(tokenPayload[key]))
      .join("&"),
    muteHttpExceptions: true
  };

  const response = UrlFetchApp.fetch(tokenUrl, options);
  const result = JSON.parse(response.getContentText());

  if (!result.access_token) {
    throw new Error(`Failed to get access token: ${response.getContentText()}`);
  }

  return result.access_token;
}

// Function to normalize a string by trimming and removing hidden characters
function normalizeString(str) {
  return str.replace(/\s+/g, ' ').trim();
}
