const crypto = require('crypto');
const express = require('express');
const bodyParser = require('body-parser');
const { WebClient } = require('@slack/web-api');
const axios = require('axios');
const config = require('./config');
const cache = require('./cache');
const dialogflowService = require('./dialogflowService');
const { hasCompletedTraining, TRAINING_REQUIRED_MESSAGE } = require('./trainingCheck');
const { hasRemedyIncidentId, hasRemedyAccess, REMEDY_ACCESS_DENIED_MESSAGE } = require('./remedyCheck');
const {feedbackButtons, disclaimer} = require('./interactive');
const { SessionsClient } = require('@google-cloud/dialogflow-cx');

const sessionClient = new SessionsClient();

// Wait message actions and endings
const waitActions = [
  "🔍 Let me quickly check our resources for you.",
  "✍️ I'm putting together the best information for you.",
  "🧐 Let me double-check that for you to be absolutely sure.",
  "📁 I'm just pulling up the right details.",
  "🛠️ I'm working on getting this sorted out for you.",
  "📖 I'm consulting our resources to find the right answer.",
  "🤔 Let me take a quick look into this for you.",
  "🔎 I'm searching our system for the most accurate details.",
  "📊 I'm compiling the correct information for you now.",
  "🎯 I'm focusing on getting you the exact info you need.",
  "💡 Let me formulate the best solution for you.",
  "⚡ I'm preparing the necessary information response for you.",
  "⚙️ I'm doing a bit of quick work behind the scenes.",
  "🕵️ I'm reviewing the details of your request right now.",
  "⭐ I'm putting together a helpful response.",
];

const waitEndings = [
  "thanks for your patience!",
  "thank you for giving me a brief moment!",
  "this will only take a moment.",
  "hang tight, I'll be right back with the answer!",
  "I appreciate you waiting.",
  "thanks for sticking with me while I check this!",
  "I appreciate your time while I get this sorted.",
  "I won't keep you waiting long!",
  "hang tight for just a second!",
  "almost there, thanks for your patience!",
  "thank you so much for your patience today.",
  "I'll have this ready for you in just a moment.",
  "I appreciate you giving me a second to look into this.",
  "thank you for waiting, I'm on it!",
  "thanks for your patience, it is highly appreciated!",
];

// Helper function to get a random wait message
function getRandomWaitMessage() {
  const randomAction = waitActions[Math.floor(Math.random() * waitActions.length)];
  const randomEnding = waitEndings[Math.floor(Math.random() * waitEndings.length)];
  return `${randomAction}, ${randomEnding}`;
}

// Build a stable key for de-duplication while preserving formatting
function buildDedupeKey(message) {
  // Keep newlines; collapse only consecutive spaces/tabs and strip CR
  return String(message)
    .replace(/\r/g, '')
    .replace(/[ \t]+/g, ' ')
    .trim();
}

function dedupeMessagesPreserveFormatting(messages) {
  const seen = new Set();
  const result = [];
  for (const message of messages) {
    const key = buildDedupeKey(message);
    if (!seen.has(key)) {
      seen.add(key);
      // Trim ends but preserve internal newlines as-is
      result.push(String(message).replace(/\r/g, '').trim());
    }
  }
  return result;
}

// Prefer the finalized platform output when available (prevents duplicate "LLM text" + finalize output).
function extractFinalizeForPlatformMessages(adkData) {
  if (!Array.isArray(adkData)) return [];
  const out = [];
  for (const item of adkData) {
    const parts = item && item.content && Array.isArray(item.content.parts) ? item.content.parts : [];
    for (const part of parts) {
      const fr = part && part.functionResponse;
      if (!fr || fr.name !== 'finalize_for_platform') continue;
      const resp = fr.response || {};
      const text = (resp.text || resp.message || '').toString().trim();
      if (text) out.push(text);
    }
  }
  return out;
}

/** show_wait_message AgentTool acknowledgments (ticket analysis, remedy, jira, etc.). */
function extractShowWaitMessageMessages(adkData) {
  if (!Array.isArray(adkData)) return [];
  const out = [];
  for (const item of adkData) {
    const parts = item?.content?.parts || [];
    for (const part of parts) {
      const fr = part?.functionResponse;
      if (!fr || fr.name !== 'show_wait_message') continue;
      const resp = fr.response || {};
      const text = (resp.message || resp.text || '').toString().trim();
      if (text) out.push(text);
    }
  }
  return out;
}

/**
 * Ordered outbound Slack messages from one /run payload.
 * When finalize_for_platform exists: show_wait_message first, then last finalize only
 * (avoids duplicate LLM draft + finalize). Otherwise fall back to legacy part collection.
 */
function collectAdkResponseMessages(adkData) {
  if (!Array.isArray(adkData)) return [];

  const waitMsgs = extractShowWaitMessageMessages(adkData);
  const finalizeMsgs = extractFinalizeForPlatformMessages(adkData);

  if (finalizeMsgs.length) {
    return [...waitMsgs, finalizeMsgs[finalizeMsgs.length - 1]];
  }

  const out = [...waitMsgs];
  for (const item of adkData) {
    if (!item.content?.parts) continue;
    const itemHasFinalize = item.content.parts.some(
      (p) => p.functionCall && p.functionCall.name === 'finalize_for_platform'
    );
    for (const part of item.content.parts) {
      if (
        !itemHasFinalize &&
        part.text &&
        (!part.functionCall || part.functionCall.name !== 'finalize_for_platform')
      ) {
        out.push(String(part.text).trim());
      }
      if (part.functionResponse && part.functionResponse.response) {
        const fr = part.functionResponse;
        if (fr.name === 'show_wait_message' || fr.name === 'finalize_for_platform') continue;
        const preferred = fr.response.message || fr.response.text;
        if (preferred) out.push(String(preferred).trim());
      }
    }
  }
  return out;
}

/** ADK returns 404 with detail like "Session not found: <session_id>" after deploy or stale Redis mapping. */
function isAdkSessionNotFoundError(err) {
  const status = err?.response?.status;
  if (status !== 404) return false;
  const data = err.response?.data;
  let detail = data?.detail;
  if (detail == null && typeof data === 'string') {
    try {
      const parsed = JSON.parse(data);
      detail = parsed?.detail;
    } catch {
      detail = data;
    }
  }
  if (typeof detail !== 'string') return false;
  return detail.includes('Session not found');
}

const ticketRegex = /\b(ticket|remedy ticket|incident ticket|summarize INC\d+|INC\d+)\b/i;
const KMSDisclaimerRegex = /^\s*\*{0,2}Disclaimer\*{0,2}\s*$/im;
const app = express();
app.use(bodyParser.json());

// Lightweight health/keep-warm endpoint for Cloud Scheduler (reduces cold starts)
app.get('/health', (req, res) => {
  res.status(200).send('ok');
});

// Use config values
const SLACK_SIGNING_SECRET = config.SLACK_SIGNING_SECRET;
const SLACK_BOT_TOKEN = config.SLACK_BOT_TOKEN;
const ADK_API_URL = config.ADK_API_URL;
const BOT_USER_ID = config.BOT_USER_ID; // Set this after installing your app
const DISCLAIMER = config.SLACK_DISCLAIMER;

const slackClient = new WebClient(SLACK_BOT_TOKEN);

const SESSION_RESET_ACK =
  "I've started a new session for you. Your previous conversation context has been cleared. Send your next question whenever you're ready.";

async function postSessionResetAck(channel, { threadTs } = {}) {
  const resetReply = { channel, text: SESSION_RESET_ACK };
  if (threadTs) resetReply.thread_ts = threadTs;
  await slackClient.chat.postMessage(resetReply);
}

function normalizeUserTextForSessionIntent(text) {
  return String(text || '')
    .replace(new RegExp(`<@${BOT_USER_ID}>`, 'gi'), '')
    .replace(/<@\w+>/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
}

/** User message is only a request to end/restart session (no other question in the same message). */
const SESSION_RESET_ONLY_RE =
  /^(?:(?:please|kindly|can you|could you|would you)\s+)?(?:(?:(?:create|start|open)\s+(?:a\s+)?new\s+session(?:\s+for\s+(?:me|us))?)|(?:(?:end|close|clear|kill|stop|reset|restart)(?:\s+my)?\s+(?:the\s+)?session)|(?:(?:new|fresh)\s+session)|(?:reset|restart)\s+(?:my\s+)?(?:session|conversation|chat))\s*[.!?]*$/;

const SESSION_RESET_INTENT_RE =
  /\b(?:(?:create|start|open)\s+(?:a\s+)?new\s+session|(?:end|close|clear|reset|restart)(?:\s+my)?\s+(?:the\s+)?session|(?:new|fresh)\s+session|reset\s+(?:my\s+)?(?:session|conversation|chat)|restart(?:\s+(?:my\s+)?(?:session|conversation|chat))?)\b/;

function isSessionResetOnlyRequest(text) {
  const t = normalizeUserTextForSessionIntent(text);
  return Boolean(t) && SESSION_RESET_ONLY_RE.test(t);
}

function isSessionResetRequest(text) {
  const t = normalizeUserTextForSessionIntent(text);
  return Boolean(t) && (SESSION_RESET_ONLY_RE.test(t) || SESSION_RESET_INTENT_RE.test(t));
}

function stripSessionResetPhrases(text) {
  let t = String(text || '')
    .replace(new RegExp(`<@${BOT_USER_ID}>`, 'gi'), '')
    .replace(/<@\w+>/g, '')
    .trim();
  const leadingPatterns = [
    /^(?:(?:please|kindly|can you|could you|would you)\s+)?(?:create|start|open)\s+(?:a\s+)?new\s+session(?:\s+for\s+(?:me|us))?\s*[,.]?\s*(?:and\s+)?/i,
    /^(?:(?:please|kindly|can you|could you|would you)\s+)?(?:end|close|clear|kill|stop|reset|restart)(?:\s+my)?\s+(?:the\s+)?session\s*[,.]?\s*(?:and\s+)?/i,
    /^(?:(?:please|kindly)\s+)?(?:new|fresh)\s+session\s*[,.]?\s*(?:and\s+)?/i,
    /^(?:reset\s+(?:my\s+)?(?:session|conversation|chat)|restart(?:\s+(?:my\s+)?(?:session|conversation|chat))?)\s*[,.]?\s*(?:and\s+)?/i,
  ];
  let changed = true;
  while (changed) {
    changed = false;
    for (const re of leadingPatterns) {
      const next = t.replace(re, '').trim();
      if (next !== t) {
        t = next;
        changed = true;
      }
    }
  }
  // Multiline Slack messages: drop leading lines that are only a session-reset phrase.
  const lines = t.split(/\n+/).map((line) => line.trim()).filter(Boolean);
  while (lines.length > 0) {
    const normalized = normalizeUserTextForSessionIntent(lines[0]);
    if (normalized && SESSION_RESET_ONLY_RE.test(normalized)) {
      lines.shift();
      continue;
    }
    break;
  }
  return lines.join(' ').replace(/\s+/g, ' ').trim();
}

/** Flush this user's Redis session mapping, then create a new ADK session (not other users). */
async function createFreshAdkSession(userId, cacheOpts, { persistWithActivity = true } = {}) {
  await cache.flushUserSessions(userId, cacheOpts);
  const sessionId = cache.getSessionIdTimeBased(userId, cacheOpts);
  const adkSessionRes = await axios.post(
    `${ADK_API_URL}/apps/wanda_chatbot/users/${userId}/sessions/${sessionId}`,
    {
      platform: 'slack',
      slackChatInterface: cacheOpts.isDM ? 'DM' : 'channel',
    },
    { headers: { 'Content-Type': 'application/json' } },
  );
  const session = adkSessionRes.data;
  const cacheKey = cache.getCacheKey(userId, cacheOpts);
  if (persistWithActivity) {
    await cache.setSessionWithActivity(userId, cacheOpts, session);
  } else {
    await cache.setSession(cacheKey, session, 1800);
  }
  console.log(`Session reset for user ${userId}: ${sessionId}`);
  return { sessionId, session, cacheKey };
}

// Helper: Verify Slack signature
function verifySlackRequest(req) {
  const timestamp = req.headers['x-slack-request-timestamp'];
  const slackSignature = req.headers['x-slack-signature'];
  if (!timestamp || !slackSignature) return false;
  // Prevent replay attacks
  if (Math.abs(Math.floor(Date.now() / 1000) - timestamp) > 60 * 5) return false;
  const sigBaseString = `v0:${timestamp}:${JSON.stringify(req.body)}`;
  const mySignature =
    'v0=' +
    crypto.createHmac('sha256', SLACK_SIGNING_SECRET)
      .update(sigBaseString)
      .digest('hex');
  try {
    return crypto.timingSafeEqual(Buffer.from(mySignature), Buffer.from(slackSignature));
  } catch {
    return false;
  }
}

async function isBotMember(channel, userId){
   try {
    let cursor;
    do {
      const response = await slackClient.conversations.members({
        channel,
        cursor,
      });

      if (response.members.includes(userId)) {
        return true;
      }

      cursor = response.response_metadata.next_cursor;
    } while (cursor);
    return false;
  } catch (error) {
    console.error('Error checking user membership:', error);
    return false;
  }
}

async function setDisclaimer(channel) {
  const convo = await slackClient.conversations.info({ channel })

  // if(!isMember && convo.ok && !convo.channel.is_im){
  //   return;
  // }

  if(convo.ok){
    let topic = `*Important:* Please review the Disclaimer before interacting with Wanda. You can always find it here:`;
    const topicSet = convo.channel.topic && convo.channel.topic.value
    if((topicSet && !convo.channel.topic.value.startsWith(topic)) || !topicSet){
      const setInitTopic = await slackClient.conversations.setTopic({ channel, topic})
      
      if(setInitTopic.ok){
        const {ts} = await disclaimer(channel, DISCLAIMER.replace(/\\n/g, '\n'));
        
        const permalinkResult = await slackClient.chat.getPermalink({ channel, message_ts:ts });
        const [topicUpdate] = await Promise.all([
          //slackClient.pins.add({ channel, timestamp: ts}),
          slackClient.conversations.setTopic({ channel, topic: topic+permalinkResult.permalink })
        ])
        if(topicUpdate.ok){
          console.info(`✅ TOPIC UPDATED`)
          //console.info(`✅ DISCLAIMER PINNED`)
          return
        }
      }
      return;
    }
  }
}

app.post('/slack/events', async (req, res) => {

    const { type, challenge, event, event_id } = req.body;

    // Handle Dialogflow callback within the same endpoint
    if (req.body.insightRecorderCallback && req.body.sessionId) {
      console.log('Received Dialogflow callback:', req.body);
      
      try {
        const result = await dialogflowService.handleDialogflowCallback(req.body);
        
        if (result.success) {
          res.status(200).json(result);
        } else {
          res.status(400).json(result);
        }
      } catch (error) {
        console.error('Error handling Dialogflow callback:', error);
        res.status(500).json({
          success: false,
          error: error.message,
          timestamp: new Date().toISOString()
        });
      }
      return; // Stop further processing for Dialogflow callback
    }

    // Slack URL verification challenge (MUST be handled first and exclusively)
    if (type === 'url_verification') {
      console.log('Responding to url_verification challenge.');
      return res.send({ challenge: challenge }); // ONLY send this response for URL verification
    }

    // Handle /flush-sessions request within /slack/events
    if (req.body.secret && req.body.secret === config.FLUSH_SECRET) {
        console.log('Processing flush-sessions request.');
        res.status(200).send({ status: 'success', message: 'Initiating session flush.' }); // Acknowledge immediately
        try {
            await cache.flushAllSessions();
            console.info('All sessions flushed successfully.');
        } catch (error) {
            console.error('Error flushing sessions:', error);
        }
        return; // Stop further processing for flush request
    }

    // Handle /purge-user-sessions request within /slack/events
    if (req.body.secret && req.body.secret === config.FLUSH_SECRET && req.body.action === 'purge-user') {
        console.log('Processing purge-user-sessions request.');
        res.status(200).send({ status: 'success', message: 'Initiating user session purge.' }); // Acknowledge immediately
        try {
            const userId = req.body.userId;
            const isDM = req.body.isDM || false;
            const threadTs = req.body.threadTs;
            
            if (!userId) {
                console.error('userId is required for user session purge');
                return;
            }
            
            const purged = await cache.flushUserSessions(userId, { isDM, channel });
            console.info(`User session purge ${purged ? 'completed' : 'failed'} for user ${userId}`);
        } catch (error) {
            console.error('Error purging user sessions:', error);
        }
        return; // Stop further processing for purge request
    }

    // For all other types of requests, acknowledge immediately (after url_verification)
    res.status(200).send();

    console.dir({ slack_request_body: req.body }, { depth: null, colors: true });

    // Verify request signature
    // if (!verifySlackRequest(req)) {
    //   console.error('Slack signature verification failed.');
    //   return; // Just return, as 200 OK already sent
    // }

    const { type: eventType ,text, user, channel, channel_type, bot_profile, thread_ts, ts, files } = event;
    console.log({ eventType, text, user, channel, channel_type, bot_profile, thread_ts, ts, files });
    // Ignore file_shared events as they contain minimal file information
    if (eventType === 'file_shared') {
      console.log('Ignoring file_shared event - waiting for message event with complete file details');
      return;
    }

    // Handle file sharing events - only process message events with files, ignore file_shared events
    if (eventType === 'message' && files && files.length > 0) {
      let channelId, messageTs, userId, messageText, channelType;
      let filesForAdk = []; // This will store all processed file details

      try {
          channelId = event.channel;
          messageTs = event.thread_ts || event.ts;
          userId = event.user;
          messageText = event.text || '';
          channelType = event.channel_type;

          const isDMFile = channelType === 'im';
          const isTaggedFile = messageText.includes(`<@${BOT_USER_ID}>`);

          // Only set disclaimer in channels when Wanda is explicitly mentioned
          if (!isDMFile && isTaggedFile) {
            await setDisclaimer(channelId);
          }

          // Domain authorization and training check for file events
          try {
            const userDetailsFile = await slackClient.users.info({ user: userId });
            const profileFile = userDetailsFile?.user?.profile || {};
            const userEmailFile = profileFile.email || '';
            const userNameFile = profileFile.real_name || userDetailsFile?.user?.name || '';
            console.log('[Auth/File] User lookup:', { userId, email: userEmailFile || '(not available)', name: userNameFile || '(not available)' });
            const userEmailDomainFile = userEmailFile ? userEmailFile.split('@')[1] : '';
            if (userEmailDomainFile !== 'consoleconnect.com') {
              console.log(`Unauthorized file event from domain: ${userEmailDomainFile}`);
              return;
            }
            const trainingResult = await hasCompletedTraining(userEmailFile, userNameFile);
            if (!trainingResult.allowed) {
              const replyOpts = { channel: channelId, text: TRAINING_REQUIRED_MESSAGE };
              if (isTaggedFile) replyOpts.thread_ts = messageTs;
              await slackClient.chat.postMessage(replyOpts);
              return;
            }
            if ((isDMFile || isTaggedFile) && hasRemedyIncidentId(messageText)) {
              const remedyResult = await hasRemedyAccess(userEmailFile, userNameFile);
              if (!remedyResult.allowed) {
                const replyOpts = { channel: channelId, text: REMEDY_ACCESS_DENIED_MESSAGE };
                if (isTaggedFile) replyOpts.thread_ts = messageTs;
                await slackClient.chat.postMessage(replyOpts);
                return;
              }
            }
          } catch (authErr) {
            console.error('Error in file event authorization:', authErr);
            return;
          }

          // Process all attached files with their complete details
          for (const file of files) {
              filesForAdk.push({
                  name: file.name,
                  url_private: file.url_private,
                  id: file.id,
                  mimetype: file.mimetype,
                  size: file.size,
                  filetype: file.filetype,
                  pretty_type: file.pretty_type,
                  permalink: file.permalink,
                  url_private_download: file.url_private_download
              });
          }

          // Determine if the message is from a DM or tagged in a channel
          const isDM = isDMFile;
          const isTagged = isTaggedFile;

          const cacheOpts = { isDM, channel: channel || '' };

          let needsFreshSession = false;
          if (isSessionResetRequest(messageText)) {
            if (isSessionResetOnlyRequest(messageText)) {
              await createFreshAdkSession(userId, cacheOpts, { persistWithActivity: false });
              await postSessionResetAck(channelId, { threadTs: isTagged ? messageTs : undefined });
              return;
            }
            messageText = stripSessionResetPhrases(messageText);
            needsFreshSession = true;
            console.log('Session reset requested (file event); continuing with new session');
          }

          // --- SESSION MANAGEMENT ---
          let sessionId, session, cacheKey;
          cacheKey = cache.getCacheKey(userId, cacheOpts);

          if (needsFreshSession) {
            const fresh = await createFreshAdkSession(userId, cacheOpts, { persistWithActivity: false });
            sessionId = fresh.sessionId;
            session = fresh.session;
          } else {
            session = await cache.getSession(cacheKey);

            if (session) {
              sessionId = session.id || cache.getSessionIdTimeBased(userId, cacheOpts);
            } else {
              sessionId = cache.getSessionIdTimeBased(userId, cacheOpts);
              const adkSessionRes = await axios.post(`${ADK_API_URL}/apps/wanda_chatbot/users/${userId}/sessions/${sessionId}`, {
                platform: "slack",
                slackChatInterface: isDM ? "DM" : "channel"
              }, { headers: { 'Content-Type': 'application/json' } });
              session = adkSessionRes.data;
              await cache.setSession(cacheKey, session, 1800);
              console.log(`New session created for file event: ${sessionId}`);
            }
          }

          // --- SEND TO ADK API SERVER ---
          if (needsFreshSession && (messageText || '').trim()) {
            await postSessionResetAck(channelId, { threadTs: isTagged ? messageTs : undefined });
          }

          const slackEventForAdk = {
            text: messageText,
            files: filesForAdk // Use the collected files here
          };


          const adkPayload = {
              app_name: 'wanda_chatbot',
              user_id: userId,
              session_id: sessionId,
              new_message: {
                  role: 'user',
                  parts: [{ text: JSON.stringify(slackEventForAdk) }]
              }
          };

          console.log('[ADK PAYLOAD SENT]', JSON.stringify(adkPayload));
          console.dir({'SLACK EVENT FOR ADK': slackEventForAdk }, { depth: null });

          let adkResponseMessages = [];
          let adkData = null; // Declared at this scope
          let waitMessageTs = null; // Track wait message timestamp
          
          // Start timing the ADK API call
          const startTime = Date.now();
          
          // Only schedule wait message in DMs or when the bot is tagged in channels
          let waitTimeout = null;
          if (isDM || isTagged) {
            waitTimeout = setTimeout(async () => {
                try {
                    const waitMsg = getRandomWaitMessage();
                    const waitResponse = await slackClient.chat.postMessage({
                        channel: channelId,
                        text: waitMsg,
                        thread_ts: isTagged ? messageTs : undefined
                    });
                    waitMessageTs = waitResponse.ts;
                    console.log('Sent wait message for file event:', waitMsg);
                } catch (waitError) {
                    console.error('Error sending wait message for file event:', waitError);
                }
            }, 5000);
          }
          
          try {
              const adkRes = await axios.post(`${ADK_API_URL}/run`, adkPayload, { headers: { 'Content-Type': 'application/json' } });
              adkData = adkRes.data; // Assigned here
              adkResponseMessages = collectAdkResponseMessages(adkData);
              if (adkResponseMessages.length === 0) adkResponseMessages.push('Sorry, there was an error.');
              
              // Clear the wait timeout since we got a response
              clearTimeout(waitTimeout);
              
              // Check if response took more than 5 seconds and send wait message if needed
              const responseTime = Date.now() - startTime;
              if (responseTime > 5000 && waitMessageTs) {
                  // Delete the wait message since we have the actual response
                  try {
                      await slackClient.chat.delete({
                          channel: channelId,
                          ts: waitMessageTs
                      });
                  } catch (deleteError) {
                      console.error('Error deleting wait message:', deleteError);
                  }
              }
          } catch (e) {
              // Clear the wait timeout since we got an error
              clearTimeout(waitTimeout);
              
              if (isAdkSessionNotFoundError(e)) {
                  console.warn('ADK session not found for file event (404), flushing Redis and creating new session...', e.response?.data?.detail);
                  const fresh = await createFreshAdkSession(userId, cacheOpts, { persistWithActivity: false });
                  sessionId = fresh.sessionId;
                  session = fresh.session;
                  cacheKey = fresh.cacheKey;

                  adkPayload.session_id = sessionId;

                  // Retry the ADK call
                  const retryAdkRes = await axios.post(`${ADK_API_URL}/run`, adkPayload, { headers: { 'Content-Type': 'application/json' } });
                  adkData = retryAdkRes.data; // Assign to the same variable
                  adkResponseMessages = collectAdkResponseMessages(adkData);
                  if (adkResponseMessages.length === 0) adkResponseMessages.push('Sorry, there was an error.');
              } else {
                  adkResponseMessages = ['Sorry, there was an error.'];
                  console.error("ADK API call failed for file event:", e);
              }
          }

          adkResponseMessages = dedupeMessagesPreserveFormatting(adkResponseMessages);

          // Start Dialogflow in parallel with reply loop so feedback goes out right after last message
          let dialogflowPromiseFile = null;
          if (isDM || isTagged) {
            let formattedUserText = messageText;
            if (filesForAdk && filesForAdk.length > 0) {
              const fileNames = filesForAdk.map(file => `[${file.name}]`).join('\n');
              formattedUserText = `${messageText}\n\n${fileNames}`;
            }
            const dialogflowPayload = {
              sessionId, userText: formattedUserText, adkResponseMessages, adkData, event, isDM, threadTs: messageTs
            };
            dialogflowPromiseFile = dialogflowService.sendToDialogflow(dialogflowPayload).catch((err) => {
              console.error('❌ Error sending file event to Dialogflow:', err);
              return { success: false, response: {} };
            });
          } else {
            console.log('Skipping Dialogflow for file event - not DM and not tagged');
          }

          // --- REPLY TO USER ---
          for (const msg of adkResponseMessages) {
              const isTaggedMsg = messageText.includes(`<@${BOT_USER_ID}>`);
              if (isTaggedMsg) {
                await slackClient.chat.postMessage({ channel: channelId, text: msg, thread_ts: messageTs });
              } else if (isDM) {
                await slackClient.chat.postMessage({ channel: channelId, text: msg });
              }
              await new Promise(res => setTimeout(res, 2000));
          }

          if (dialogflowPromiseFile) {
            try {
              const dialogflowResult = await dialogflowPromiseFile;
              const responseId = dialogflowResult?.response?.responseId;
              if (responseId) {
                const sessionPath = sessionClient.projectLocationAgentSessionPath(
                  config.DIALOGFLOW.PROJECT_ID,
                  config.DIALOGFLOW.LOCATION,
                  config.DIALOGFLOW.AGENT_ID,
                  sessionId
                );
                const feedbackTs = (isDM) ? null : messageTs || null;
                await feedbackButtons(sessionPath, responseId, channelId, userId, feedbackTs);
              }
              if (dialogflowResult?.success) {
                console.log('✅ Successfully sent file event to Dialogflow external conversational agent');
              }
            } catch (err) {
              console.error('Error posting feedback after file event:', err);
            }
          }

      } catch (error) {
          console.error('Error in file event handling:', error);
      }
      return;
    }

    // Continue with existing message handling logic if not a file event
    // Only handle message events (excluding file_shared events which are ignored)
    console.dir({ event }, { depth: null, colors: true });

    if (!event || eventType !== 'message') { // Only process messages without files from here
      console.log(`Ignoring event type '${eventType}' as it's not a message event.`);
      return; // Not a message event to process further
    }

    // Deduplication: check if event_id already processed
    if (event_id) {
      const dedupKey = `slack-event-${event_id}`;
      const alreadyProcessed = await cache.getSession(dedupKey);
      if (alreadyProcessed) {
        console.log(`Duplicate event_id received, skipping: ${event_id}`);
        return; // Already processed, ignore
      }
      await cache.setSession(dedupKey, { processed: true }, 300); // 5 min TTL
    }

    // Ignore messages from the bot itself
    if (user === BOT_USER_ID) {
      console.log('Ignoring message from bot itself.');
      return;
    }

    // Domain authorization check
    let userEmail = '';
    let userName = '';
    try {
      const userDetails = await slackClient.users.info({ user });
      if (userDetails.ok && userDetails.user) {
        const profile = userDetails.user.profile || {};
        userEmail = profile.email || '';
        userName = profile.real_name || userDetails.user.name || '';
      }
      console.log('[Auth] User lookup:', { userId: user, email: userEmail || '(not available)', name: userName || '(not available)' });
      const userEmailDomain = userEmail ? userEmail.split('@')[1] : '';
      if (userEmailDomain !== 'consoleconnect.com') {
        console.log(`Unauthorized: Ignoring event type '${eventType}' in context '${channel_type}' triggered by '${userEmailDomain}'`);
        return;
      }
    } catch (error) {
      console.error('Error checking user authorization:', error);
      return; // Fail secure - deny access if we can't verify
    }

    // Check if DM or tagged in channel
    const isDM = channel_type === 'im';
    const isTagged = text && text.includes(`<@${BOT_USER_ID}>`);
    const mentionMatches = text ? text.match(/<@\w+>/g) : null;
    const isMentioned = mentionMatches && mentionMatches.length > 1; // More than just the bot

    // Only set disclaimer in channels when Wanda is explicitly invoked
    if (!isDM && isTagged && !isMentioned) {
      await setDisclaimer(channel);
    }

    // Training data verification - only when Wanda is actually invoked (DM or tagged)
    // Try email first, then fallback to First_Name + Last_Name / local-part match
    if (isDM || isTagged) {
      const trainingResult = await hasCompletedTraining(userEmail, userName, user);
      if (!trainingResult.allowed) {
        const replyOpts = { channel, text: TRAINING_REQUIRED_MESSAGE };
        if (!isDM && isTagged) replyOpts.thread_ts = ts;
        await slackClient.chat.postMessage(replyOpts);
        return;
      }
      if (hasRemedyIncidentId(text)) {
        const remedyResult = await hasRemedyAccess(userEmail, userName);
        if (!remedyResult.allowed) {
          const replyOpts = { channel, text: REMEDY_ACCESS_DENIED_MESSAGE };
          if (!isDM && isTagged) replyOpts.thread_ts = ts;
          await slackClient.chat.postMessage(replyOpts);
          return;
        }
      }
    }

    // Check for "remedy ticket" in non-DM channels only if app is mentioned/tagged
    if (!isDM && isTagged && ticketRegex.test(text)) {
      console.log('Detected remedy ticket request in a public channel. Responding with confidentiality message.');
      await slackClient.chat.postMessage({
        channel: channel,
        text: "Remedy tickets involve customer information and service-related data that constitute confidential information. According to the information security policy, it is inappropriate to disclose or share any confidential information over a Slack channel. If you are an authorized user allowed to access the Remedy ticket system, please make your request through a direct message to me.",
        thread_ts: ts
      });
      return; // Stop further processing
    }

    // Main processing for non-file messages
    if (isDM || (isTagged && !isMentioned)) {
      // --- SESSION MANAGEMENT ---
      let sessionId, session, cacheKey, threadTs;
      const cacheOpts = { isDM, channel: isDM ? '' : channel };
      threadTs = isDM ? ts : (thread_ts || ts);
      let userRequestedSessionReset = false;

      if (isSessionResetRequest(text)) {
        userRequestedSessionReset = true;
        if (isSessionResetOnlyRequest(text)) {
          await createFreshAdkSession(user, cacheOpts);
          await postSessionResetAck(channel, { threadTs: isDM ? undefined : threadTs });
          return;
        }
        text = stripSessionResetPhrases(text);
        console.log('Session reset requested; continuing with new session');
      }

      let freshSession = null;
      if (userRequestedSessionReset) {
        freshSession = await createFreshAdkSession(user, cacheOpts);
      }

      if (isDM) {
        console.log('Processing a direct message event.');

        if (freshSession) {
          sessionId = freshSession.sessionId;
          session = freshSession.session;
          cacheKey = freshSession.cacheKey;
        } else {
          // Get session with automatic idle checking and purging
          session = await cache.getSessionWithIdleCheck(user, { isDM: true });

          if (session) {
            sessionId = session.id || cache.getSessionIdTimeBased(user, { isDM: true });
            console.log(`Using existing session for DM: ${sessionId}`);
          } else {
            sessionId = cache.getSessionIdTimeBased(user, { isDM: true });
            const adkSessionRes = await axios.post(`${ADK_API_URL}/apps/wanda_chatbot/users/${user}/sessions/${sessionId}`, {
              platform: "slack",
              slackChatInterface: "DM"
            }, { headers: { 'Content-Type': 'application/json' } });
            session = adkSessionRes.data;
            await cache.setSessionWithActivity(user, { isDM: true }, session);
            console.log(`New session created for DM: ${sessionId}`);
          }
        }

      } else if (isTagged && !isMentioned) {
        if (freshSession) {
          sessionId = freshSession.sessionId;
          session = freshSession.session;
          cacheKey = freshSession.cacheKey;
        } else {
          session = await cache.getSessionWithIdleCheck(user, { isDM: false, channel });

          if (session) {
            sessionId = session.id || cache.getSessionIdTimeBased(user, { isDM: false, channel });
            console.log(`Using existing session for tagged message: ${sessionId}`);
          } else {
            sessionId = cache.getSessionIdTimeBased(user, { isDM: false, channel });
            const adkSessionRes = await axios.post(`${ADK_API_URL}/apps/wanda_chatbot/users/${user}/sessions/${sessionId}`, {
              platform: "slack",
              slackChatInterface: "channel"
            }, { headers: { 'Content-Type': 'application/json' } });
            session = adkSessionRes.data;
            await cache.setSessionWithActivity(user, { isDM: false, channel }, session);
            console.log(`New session created for tagged message: ${sessionId}`);
          }
        }
      }

      // --- SEND TO ADK API SERVER ---
      let adkResponseMessages = [];
      let adkData = null; // Declare adkData at this scope
      const messageToSend = (text || '').trim(); // Normal message text (may be stripped after session reset)

      if (userRequestedSessionReset && !messageToSend) {
        await createFreshAdkSession(user, cacheOpts);
        await postSessionResetAck(channel, { threadTs: isDM ? undefined : threadTs });
        return;
      }

      if (userRequestedSessionReset && messageToSend) {
        await postSessionResetAck(channel, { threadTs: isDM ? undefined : threadTs });
      }

      const adkPayload = {
        app_name: 'wanda_chatbot',
        user_id: user,
        session_id: sessionId,
        new_message: {
          role: 'user',
          parts: [{ text: messageToSend }]
        }
      };

      console.log('[ADK PAYLOAD SENT]', JSON.stringify(adkPayload)); // Log the payload

      let waitMessageTs = null; // Track wait message timestamp
      
      // Start timing the ADK API call
      const startTime = Date.now();
      
      // Set up a timeout to send wait message after 5 seconds
      const waitTimeout = setTimeout(async () => {
          try {
              const waitMsg = getRandomWaitMessage();
              const waitResponse = await slackClient.chat.postMessage({
                  channel: channel,
                  text: waitMsg,
                  thread_ts: isDM ? undefined : threadTs
              });
              waitMessageTs = waitResponse.ts;
              console.log('Sent wait message for regular message:', waitMsg);
          } catch (waitError) {
              console.error('Error sending wait message for regular message:', waitError);
          }
      }, 5000);

      try {
        const adkRes = await axios.post(`${ADK_API_URL}/run`, adkPayload, { headers: { 'Content-Type': 'application/json' } });
        adkData = adkRes.data; // Assign to the declared variable
        console.dir({ adk_response: adkData }, { depth: null, colors: true });
        adkResponseMessages = collectAdkResponseMessages(adkData);
        if (adkResponseMessages.length === 0) adkResponseMessages.push('Sorry, there was an error.');
        
        // Clear the wait timeout since we got a response
        clearTimeout(waitTimeout);
        
        // Check if response took more than 5 seconds and delete wait message if needed
        const responseTime = Date.now() - startTime;
        if (responseTime > 5000 && waitMessageTs) {
            // Delete the wait message since we have the actual response
            try {
                await slackClient.chat.delete({
                    channel: channel,
                    ts: waitMessageTs
                });
            } catch (deleteError) {
                console.error('Error deleting wait message:', deleteError);
            }
        }
      } catch (e) {
        // Clear the wait timeout since we got an error
        clearTimeout(waitTimeout);
        
        if (isAdkSessionNotFoundError(e)) {
          console.warn('ADK session not found (404), flushing Redis and creating new session...', e.response?.data?.detail);
          const fresh = await createFreshAdkSession(user, cacheOpts);
          sessionId = fresh.sessionId;
          session = fresh.session;
          cacheKey = fresh.cacheKey;

          adkPayload.session_id = sessionId;

          // Retry the ADK call
          const retryAdkRes = await axios.post(`${ADK_API_URL}/run`, adkPayload, { headers: { 'Content-Type': 'application/json' } });
          adkData = retryAdkRes.data; // Assign to the same variable
          if (!adkResponseMessages.length) {
            adkResponseMessages = collectAdkResponseMessages(adkData);
          }
          if (adkResponseMessages.length === 0) adkResponseMessages.push('Sorry, there was an error.');
        } else {
          adkResponseMessages = ['Sorry, there was an error.'];
          console.error("ADK API call failed for message event:", e);
        }
      }

      adkResponseMessages = dedupeMessagesPreserveFormatting(adkResponseMessages); // Deduplicate messages

      // Start Dialogflow call in parallel with reply loop so feedback can go out right after last message
      const dialogflowPayload = {
        sessionId: sessionId,
        userText: text,
        adkResponseMessages: adkResponseMessages,
        adkData: adkData,
        event: event,
        isDM,
        threadTs
      };
      const dialogflowPromise = dialogflowService.sendToDialogflow(dialogflowPayload).catch((err) => {
        console.error('❌ Error sending to Dialogflow (non-blocking):', err);
        return { success: false, response: {} };
      });

      // --- REPLY TO USER ---
      for (const msg of adkResponseMessages) {
        if (isDM) {
          await slackClient.chat.postMessage({ channel: channel, text: msg });
        } else {
          await slackClient.chat.postMessage({ channel: channel, text: msg, thread_ts: threadTs });
        }
        await new Promise(res => setTimeout(res, 2000));
      }

      // Post feedback right after replies: Dialogflow ran in parallel, so we usually have responseId ready
      try {
        const dialogflowResult = await dialogflowPromise;
        const responseId = dialogflowResult?.response?.responseId;
        if (responseId) {
          const sessionPath = sessionClient.projectLocationAgentSessionPath(
            config.DIALOGFLOW.PROJECT_ID,
            config.DIALOGFLOW.LOCATION,
            config.DIALOGFLOW.AGENT_ID,
            sessionId
          );
          const feedbackTs = (isDM) ? null : threadTs || null;
          await feedbackButtons(sessionPath, responseId, channel, user, feedbackTs);
        }
        if (dialogflowResult?.success) {
          console.log('✅ Successfully sent to Dialogflow external conversational agent');
        }
      } catch (error) {
        console.error('Error posting feedback or after Dialogflow:', error);
      }
    } else {
      // Ignore all other messages (including if just mentioned but not tagged, or unhandled event types)
      console.log(`Ignoring event: type '${eventType}', channel '${channel}', user '${user}'.`);
    }
  });

// Efficient idle session management using 5-minute activity TTL
console.log('Idle session management enabled with 5-minute activity tracking');



// Export for Google Cloud Functions
exports.slackWebhook = app;