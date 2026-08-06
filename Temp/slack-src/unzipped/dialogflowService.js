const { SessionsClient } = require('@google-cloud/dialogflow-cx');
const { WebClient } = require('@slack/web-api');
const axios = require('axios');
const config = require('./config');
const cache = require('./cache');
const { struct } = require('pb-util');

class DialogflowService {
  constructor() {
    this.projectId = config.DIALOGFLOW.PROJECT_ID;
    this.location = config.DIALOGFLOW.LOCATION;
    this.agentId = config.DIALOGFLOW.AGENT_ID;
    
         // Initialize Dialogflow CX client
     this.sessionsClient = new SessionsClient({
       apiEndpoint: `${this.location}-dialogflow.googleapis.com`,
     });
     
     // Initialize Slack client for additional context
     this.slackClient = new WebClient(config.SLACK_BOT_TOKEN);
    
    // Use cache for storing bot responses instead of in-memory storage
    // No TTL needed as cache handles session lifecycle
    
    console.log('DialogflowService constructor - Configuration values:', {
      projectId: this.projectId,
      location: this.location,
      agentId: this.agentId
    });
    
    // Validate required configuration
    if (!this.projectId) {
      console.error('❌ DIALOGFLOW_PROJECT_ID environment variable is not set');
    }
    if (!this.location) {
      console.error('❌ DIALOGFLOW_LOCATION environment variable is not set');
    }
    if (!this.agentId) {
      console.error('❌ DIALOGFLOW_AGENT_ID environment variable is not set');
    }
  }

  /**
   * Send user message to Dialogflow external conversational agent
   * @param {Object} data - Interaction data
   * @param {string} data.sessionId - Session ID
   * @param {string} data.userText - User's original message
   * @param {Array} data.adkResponseMessages - Bot's response messages from ADK
   * @param {Array} data.adkData - Full ADK response data for author extraction
   * @param {Object} data.event - Slack event data for additional context
   */
  async sendToDialogflow(data) {
    try {
      // Validate configuration before proceeding
      if (!this.projectId || !this.location || !this.agentId) {
        console.error('❌ Dialogflow configuration is incomplete. Required environment variables are missing.');
        console.error('Missing configuration:', {
          projectId: !!this.projectId,
          location: !!this.location,
          agentId: !!this.agentId
        });
        return {
          success: false,
          error: 'Dialogflow configuration is incomplete. Please set the required environment variables.'
        };
      }

      console.log('=== DIALOGFLOW SERVICE DEBUG ===');
      console.log('Configuration:', {
        projectId: this.projectId,
        location: this.location,
        agentId: this.agentId
      });
      console.log('Input Data:', {
        sessionId: data.sessionId,
        userText: data.userText,
        adkResponseMessagesCount: data.adkResponseMessages ? data.adkResponseMessages.length : 0,
        adkDataCount: data.adkData ? data.adkData.length : 0
      });

      // Store bot response and ADK data for callback retrieval
      await this.storeBotResponse(data.sessionId, data.adkResponseMessages, data.adkData);

      // Create session path
      const sessionPath = this.sessionsClient.projectLocationAgentSessionPath(
        this.projectId,
        this.location,
        this.agentId,
        data.sessionId
      );

      // Prepare the request for Dialogflow
      const dialogflowText = `[session_id:${data.sessionId}] ${data.userText}`;
      
             // Build additional parameters if event data is available
       let queryParams = {};
       if (data.event) {
         const { user, channel, channel_type, thread_ts, ts, files } = data.event;
         
         // Extract user ID from session ID (format: slack-{userId}-{thread}-{timeSlice})
         const sessionIdParts = data.sessionId.split('-');
         const extractedUserId = sessionIdParts.length >= 2 ? sessionIdParts[1] : user || '';
         
         // Get user info if available using the extracted user ID
         let userEmail = '';
         let userTimezone = '';
         let teamId = '';
         let fullName = '';
                   try {
            if (extractedUserId) { // Only try if we have a user ID
              const userInfo = await this.slackClient.users.info({ user: extractedUserId });
              if (userInfo?.ok && userInfo.user?.profile) {
                userEmail = userInfo.user.profile.email || '';
                userTimezone = userInfo.user.tz || '';
                teamId = userInfo.user.team_id || '';
                fullName = userInfo.user.profile.real_name || '';
              }
            }
          } catch (error) {
            console.log('Could not fetch user info (this is normal for some user types):', error.message);
            // Don't log as error since this is expected for some users
          }
         
         // Get channel info if available
         let channelName = '';
                   try {
            if (channel) { // Only try if we have a channel ID
              const channelInfo = await this.slackClient.conversations.info({ channel });
              if (channelInfo?.ok && channelInfo.channel?.name) {
                channelName = channelInfo.channel.name;
              }
            }
          } catch (error) {
            console.log('Could not fetch channel info (this is normal for some channel types):', error.message);
            // Don't log as error since this is expected for some channels
          }
         
         queryParams = {
           channel: channelName,
           enableResourceProjectOverride: true,
           sessionInfo: {
             parameters: struct.encode({
              slack_user_id: extractedUserId,
              slack_user_email: userEmail,
              slack_user_timezone: userTimezone,
              slack_channel_name: channelName,
              slack_channel_type: channel_type || '',
              slack_message_ts: ts || '',
              slack_team_id: teamId,
              is_in_thread: thread_ts ? 1 : 0,
              slack_thread_ts: thread_ts || ''
             })
           },
            payload: struct.encode({
              data: {
                channel_id: channel || '',
                channel_type: channel_type === 'group' ? channelName : (channel_type || ''),
                text: data.userText || '',
                user_id: extractedUserId,
                email: userEmail,
                team_id: teamId,
                full_name: fullName,
                files: files || []
              }
            })
         };
       }
      
        const request = {
          session: sessionPath,
          queryInput: {
            text: {
              text: dialogflowText
            },
            languageCode: 'en'
          },
          queryParams: { ...queryParams }
        };

       console.log('=== DIALOGFLOW REQUEST DETAILS ===');
       console.log('Session Path:', sessionPath);
       console.log('Dialogflow Text:', dialogflowText);
       console.log('Language Code: en');
       console.log('Query Parameters:', JSON.stringify(queryParams, null, 2));
       console.log('Full Request Object:', JSON.stringify(request, null, 2));
       console.log('=== END DIALOGFLOW REQUEST DETAILS ===');

      // Send request to Dialogflow
      console.log('Sending request to Dialogflow...');
      const [response] = await this.sessionsClient.detectIntent(request);
      
      console.log('✅ Dialogflow response received');
      console.log('Dialogflow Response:', JSON.stringify(response, null, 2));
      
      return {
        success: true,
        sessionId: data.sessionId,
        response: response
      };

    } catch (error) {
      console.error('❌ Error sending to Dialogflow external conversational agent:', error);
      console.error('Error details:', {
        message: error.message,
        code: error.code,
        status: error.status,
        stack: error.stack
      });
      return {
        success: false,
        error: error.message
      };
    }
  }

  /**
   * Handle callback from Dialogflow external conversational agent
   * @param {Object} requestData - Request data from Dialogflow
   * @returns {Object} Response with bot response and metadata
   */
  async handleDialogflowCallback(requestData) {
    try {
      console.log('Handling Dialogflow callback:', requestData);

      const { sessionId, insightRecorderCallback } = requestData;
      
      if (!sessionId) {
        throw new Error('Session ID is required for callback');
      }

      if (!insightRecorderCallback) {
        throw new Error('insightRecorderCallback flag is required');
      }

      // Retrieve stored bot response and ADK data
      const storedData = await this.getBotResponse(sessionId);
      
      if (!storedData) {
        throw new Error('Bot response not found for session ID: ' + sessionId);
      }

      // Clean up stored response
      await this.removeBotResponse(sessionId);

      // Get conversation authors from ADK response
      console.log('ADK Data for author extraction:', JSON.stringify(storedData.adkData, null, 2));
      const conversationAuthors = this.extractConversationAuthors(storedData.adkData);
      console.log('Extracted conversation authors:', conversationAuthors);

      // Consolidate bot response messages into a single string
      const botResponse = this.consolidateBotResponse(storedData.adkResponseMessages);

      console.log('Building response with conversationAuthors:', conversationAuthors);
      console.log('conversationAuthors type:', typeof conversationAuthors);
      console.log('conversationAuthors length:', conversationAuthors ? conversationAuthors.length : 'null');
      
      const response = {
        metadata: {
          sessionId: sessionId,
          source: 'wanda-adk-slack-webhook',
          conversationAuthors: conversationAuthors
        },
        success: true,
        botResponse: botResponse,
        timestamp: new Date().toISOString()
      };
      
      console.log('Final response being returned:', JSON.stringify(response, null, 2));
      return response;

    } catch (error) {
      console.error('Error handling Dialogflow callback:', error);
      return {
        success: false,
        error: error.message,
        timestamp: new Date().toISOString()
      };
    }
  }

  /**
   * Extract conversation authors from ADK response data
   * @param {Array} adkData - Full ADK response data
   * @returns {Array} Array of conversation authors
   */
  extractConversationAuthors(adkData) {
    const authors = [];
    
    console.log('Extracting authors from ADK data:', {
      isArray: Array.isArray(adkData),
      length: adkData ? adkData.length : 'null'
    });
    
    // Extract authors from ADK response data
    if (Array.isArray(adkData)) {
      adkData.forEach((item, index) => {
        console.log(`Item ${index}:`, JSON.stringify(item, null, 2));
        
        // Check if item has text content (either text or functionResponse with message)
        let hasTextContent = false;
        let foundTextContent = '';
        
        if (item.content && Array.isArray(item.content.parts)) {
          const itemHasFinalize = item.content.parts.some(p => p.functionCall && p.functionCall.name === 'finalize_for_platform');
          for (const part of item.content.parts) {
            // Only treat plain text as content if this item does NOT contain finalize_for_platform
            if (!itemHasFinalize && part.text && (!part.functionCall || part.functionCall.name !== 'finalize_for_platform')) {
              hasTextContent = true;
              foundTextContent = String(part.text).trim();
              console.log(`Found text content: ${foundTextContent}`);
              break;
            }
            // Treat any functionResponse as content; prefer .response.text for finalize_for_platform
            if (
              part.functionResponse &&
              part.functionResponse.response
            ) {
              const fr = part.functionResponse;
              const preferred = fr.name === 'finalize_for_platform'
                ? (fr.response.text || fr.response.message)
                : (fr.response.message || fr.response.text);
              if (preferred) {
                hasTextContent = true;
                foundTextContent = String(preferred).trim();
                console.log(`Found functionResponse content: ${foundTextContent}`);
                break;
              }
            }
          }
        }
        
        // Only add author if item has text content
        if (item.author && hasTextContent) {
          console.log(`✅ Found author with text content: ${item.author} (text: "${foundTextContent}")`);
          authors.push(item.author);
        } else if (item.author) {
          console.log(`❌ Found author but no text content: ${item.author} (skipping)`);
        } else {
          console.log(`❌ No author found in item ${index}`);
        }
      });
    }
    
    console.log('Final authors list:', authors);
    return authors;
  }

  /**
   * Consolidate bot response messages into a single string
   * @param {Array} adkResponseMessages - Array of response messages
   * @returns {string} Consolidated bot response
   */
  consolidateBotResponse(adkResponseMessages) {
    if (!Array.isArray(adkResponseMessages) || adkResponseMessages.length === 0) {
      return 'Sorry, there was an error processing your request.';
    }

    // De-duplicate while preserving newlines/formatting
    const seen = new Set();
    const normalized = [];
    for (const msg of adkResponseMessages) {
      const key = String(msg).replace(/\r/g, '').replace(/[ \t]+/g, ' ').trim();
      if (!seen.has(key)) {
        seen.add(key);
        normalized.push(String(msg).replace(/\r/g, '').trim());
      }
    }

    // Join all messages with proper formatting
    return normalized.join('\n\n');
  }

  /**
   * Store bot response for later retrieval
   * @param {string} sessionId - Session identifier (time-based ADK sessionId)
   * @param {Array} adkResponseMessages - Bot response messages to store
   * @param {Array} adkData - Full ADK response data to store
   */
  async storeBotResponse(sessionId, adkResponseMessages, adkData) {
    // Use the actual sessionId (time-based) for insight recorder storage
    // This matches what Dialogflow will call back with
    const insightRecorderKey = `${sessionId}-insightRecorder`;
    const data = {
      adkResponseMessages: adkResponseMessages,
      adkData: adkData,
      timestamp: Date.now()
    };
    
    // Store with 5-minute TTL - independent of session management
    await cache.setSession(insightRecorderKey, data, 300); // 5 minutes
    console.log(`Stored insight recorder data for session: ${sessionId} (5min TTL)`);
  }

  /**
   * Retrieve stored bot response
   * @param {string} sessionId - Session identifier (time-based ADK sessionId)
   * @returns {Object|null} Stored bot response data or null if not found/expired
   */
  async getBotResponse(sessionId) {
    // Use the actual sessionId (time-based) for insight recorder retrieval
    // This matches what Dialogflow will call back with
    const insightRecorderKey = `${sessionId}-insightRecorder`;
    const stored = await cache.getSession(insightRecorderKey);
    
    if (!stored) {
      console.log(`No insight recorder data found for session: ${sessionId} (expired or not found)`);
      return null;
    }

    console.log(`Retrieved insight recorder data for session: ${sessionId}`);
    return stored;
  }

  /**
   * Remove stored bot response
   * @param {string} sessionId - Session identifier (time-based ADK sessionId)
   */
  async removeBotResponse(sessionId) {
    // Use the actual sessionId (time-based) for insight recorder cleanup
    // This matches what Dialogflow will call back with
    const insightRecorderKey = `${sessionId}-insightRecorder`;
    await cache.deleteSession(insightRecorderKey);
    console.log(`Removed insight recorder data for session: ${sessionId}`);
  }
}

// Create singleton instance
module.exports = new DialogflowService(); 