const functions = require('@google-cloud/functions-framework');
const config = require('./config');
const AuthService = require('./auth');
const https = require('https');
const axios = require('axios');
const { DlpServiceClient } = require('@google-cloud/dlp');
const { VertexAI } = require('@google-cloud/vertexai');
const redis = require('redis');
const { getInitialMessage } = require('./initialEmailReducer');

/**
 * Request validation for webhook integration
 */
function validateRequest(body) {
  const errors = [];
  
  // For ticket_creation intent, ticketId is not required (can be empty/null/undefined) but ticketCreationPayload is
  if (body.intent === 'ticket_creation') {
    if (!body.ticketCreationPayload) {
      errors.push('ticketCreationPayload is required for ticket_creation intent');
    } else if (typeof body.ticketCreationPayload !== 'object') {
      errors.push('ticketCreationPayload must be a JSON object');
    }
    // ticketId is optional for ticket_creation - if provided, it will be ignored
  } else {
    // For other intents, ticketId is required
    if (!body.ticketId) {
      errors.push('ticketId is required');
    } else if (!/^INC\d+$/.test(body.ticketId)) {
      errors.push('ticketId must be in format INC followed by numbers');
    }
  }
  
  if (body.intent && !['summary', 'detailed', 'custom', 'rfo_report', 'customer_incident_report', 'ticket_creation'].includes(body.intent)) {
    errors.push('intent must be one of: summary, detailed, custom, rfo_report, customer_incident_report, ticket_creation');
  }
  
  if (body.prompt && typeof body.prompt !== 'string') {
    errors.push('prompt must be a string');
  }
  
  if (body.prompt && body.prompt.length > 1000) {
    errors.push('prompt must be less than 1000 characters');
  }
  
  return errors;
}

/**
 * Get error suggestions for webhook debugging
 */
function getErrorSuggestions(error) {
  if (error.message.includes('authentication')) {
    return ['Check API credentials', 'Verify token validity'];
  }
  if (error.message.includes('not found')) {
    return ['Verify ticket ID format', 'Check if ticket exists'];
  }
  if (error.message.includes('timeout')) {
    return ['Try again later', 'System may be experiencing high load'];
  }
  return ['Try again later', 'Contact support if issue persists'];
}

/**
 * Checks if a ticket is an IT helpdesk ticket based on notes
 * @param {Object} ticketData - The ticket data from Helix API
 * @returns {boolean} True if it's an IT helpdesk ticket
 */
function isITHelpdeskTicket(ticketData) {
  if (!ticketData || !Array.isArray(ticketData.notes)) {
    return false;
  }

  return ticketData.notes.some(note => 
    note.id === 'category' &&
    note.text === 'IT Supports' &&
    note['@type'] === 'faultsymptom'
  );
}

/**
 * Webhook-optimized prompt templates for consistent output
 */
const WEBHOOK_PROMPT_TEMPLATES = {
  summary: `You are a Remedy incident summarizer for Slack integration. Generate a summary in the following EXACT format:

- _--- Summary ---_
    - [Provide a summary in around 100-200 words, with creation and closure timestamps, status of the ticket, symptom, fault cause, whether it was escalated etc, in a structured paragraph.]
    - Incident number: [Incident number(s)]
    - Ticket Start: [0000 UTC XX Month YYYY]
    - Ticket End: [0000 UTC XX Month YYYY]  [If the ticket is resolved/closed, use the closure timestamp. If not, leave blank or state 'N/A.']
    - Ticket Duration: [1] day, [3] hours, [27] minutes  [If the ticket is resolved/closed, use the total duration from start to end. If not, use 'Ongoing.']
    - Severity: [Low/Medium/High or as per PCCWG scheme]
    - Status: [Use the final status value from the provided ticket data. If the ticket is resolved/closed, use that status even if earlier statuses exist.]
    - Vendor: [List vendor names if available, or N/A if no vendors are involved]
    - Customer: [Customer Name]
    - Symptom: [briefly describe the symptom]
    - Related incidents: [Incident numbers or N/A]
    - Root Cause: [briefly describe the cause of the ticket or N/A]

IMPORTANT: Use the exact field names and format above. Do not add extra formatting or change the structure. Do NOT use Q&A or bullet points. Only use the format below.
IMPORTANT: Your summary must be between 300 and 3000 words. If the ticket data is insufficient, elaborate with plausible details based on the provided information, but do not fabricate facts.

Ticket Data:
{data}`,

  detailed: `You are a Remedy incident analyst for Slack integration. Generate a comprehensive report in the following EXACT format:

- Incident Report
    - Incident number: [Incident number(s)]
    - Ticket Start: [0000 UTC XX Month YYYY]
    - Ticket End: [0000 UTC XX Month YYYY]  [If the ticket is resolved/closed, use the closure timestamp. If not, leave blank or state 'N/A.']
    - Ticket Duration: [1] day, [3] hours, [27] minutes  [If the ticket is resolved/closed, use the total duration from start to end. If not, use 'Ongoing.']
    - Severity: [Low/Medium/High or as per PCCWG scheme]
    - Status: [Use the final status value from the provided ticket data. If the ticket is resolved/closed, use that status even if earlier statuses exist.]
    - Vendor: [List vendor names if available, or N/A if no vendors are involved]
    - Customer: [Customer Name]
    - Symptom: [briefly describe the symptom]
    - Related incidents: [Incident numbers or N/A]
    - Root Cause: [briefly describe the cause of the ticket or N/A]
    - Overview
        - [An executive summary, summarize the issue, impact, cause, and actions performed for resolution in a paragraph. For example:]
        - A damaged XYZ card caused all customers connected to 10GE ports on Router X to experience packet loss. Router X became unresponsive to remote login, so an emergency outage window was scheduled to restart the router and investigate the issue. During the outage window, the XYZ card was replaced, which restored service to all affected customers. All field staff in the region will receive refresher training on card handling practices in the coming quarter.
    - Key findings
        - [Brief bullet points. What was discovered during investigation - how was the issue first detected or proven, how was it eventually resolved, what was/can be done about it? For example:]
        - Customer X reported packet loss on Y service before router X became unresponsive
        - A damaged card in router X was found to be the cause of the issue
        - Card handling processes will be reviewed and refresher training provided to staff
    - Impact
        - [What was the impact, and who (which customers or stakeholders, what (what equipment or service types), where (which locations) did it impact? For example:]
        - This issue affected all customers connected to 10GE ports on router X.
    - Incident timeline
        - [Single-sentence timestamped summaries of key moments, such as time of detection and notification. For example:]
        - DD-MMM-YYYY 0000 UTC +0: Customer X reported issue Y
        - DD-MMM-YYYY 0000 UTC +0: Router X became unresponsive
        - DD-MMM-YYYY 0000 UTC +0: Field technicians arrived at site and restarted router X
        - DD-MMM-YYYY 0000 UTC +0: Service restored
        - DD-MMM-YYYY 0000 UTC +0: Vendor recommended card replacement
        - DD-MMM-YYYY 0000 UTC +0: Card replaced during emergency outage window
        - DD-MMM-YYYY 0000 UTC +0: Vendor investigation revealed the card was damaged
    - Immediate actions
        - [Immediate actions taken to address the issue as the event unfolded. For example:]
        - Router X was restarted.
    - Resolution and root cause
        - [The issue was resolved by…For example:]
        - The issue was resolved by replacing a XYZ card in router X.
        - [The root cause of the issue was determined to be…For example:]
        - The root cause of the issue was determined to be a XYZ card that had become damaged.
    - Preventative action (if applicable)
        - [Describe any action taken or planned to prevent future occurrences of this issue,or issues of this nature.For example:]
        - Review card handling practices and issue refresher training to field staff
    - Technical timeline
        - [A timestamped, play-by-play, technically detailed description of what happened and what was done]
        - DD-MMM-YYYY 0000 UTC +0
        - [Summary of what happened at this point in time, provide insightful content]
        - DD-MMM-YYYY 0000 UTC +0
        - [Summary of what happened at this point in time, provide insightful content]
        - DD-MMM-YYYY 0000 UTC +0
        - [Summary of what happened at this point in time, provide insightful content]
        - DD-MMM-YYYY 0000 UTC +0
        - [Summary of what happened at this point in time, provide insightful content]

IMPORTANT: Use the exact field names and format above. Do not add extra formatting or change the structure. Do NOT use Q&A or bullet points. Only use the format below.
IMPORTANT: Your report must be between 1000 and 5000 words. If the ticket data is insufficient, elaborate with plausible details based on the provided information, but do not fabricate facts.

Ticket Data:
{data}`,

  custom: `You are a Remedy incident assistant for Slack integration. Answer this specific question about the ticket:

Question: {question}

IMPORTANT: The ticket data below is for ticket {ticketId}. If the question asks about a different ticket ID, please clearly state that you cannot provide information for that ticket and explain that the data provided is for ticket {ticketId}.
IMPORTANT: If the question asks about the ticket status, always use the final status value from the provided ticket data.

Provide a clear, concise answer based on the ticket data below. If the information is not available in the ticket data, please state that clearly.

Format your response for Slack markdown (use * for bold, not **).

Ticket Data:
{data}`,

  customer_incident_report: `You are generating a customer-facing incident report. Follow the EXACT structure below and keep wording professional, concise, and neutral. Use only the fields requested. DO NOT add any introductory text, closing remarks, follow-up questions, emojis, marketing language, or any content not explicitly specified. All times must use the format "DD MMM YYYY HH:MM GMT".

CRITICAL RULES:
- Extract data ONLY from the provided Ticket Data below. Do NOT hallucinate, fabricate, or invent any information.
- Replace ALL square-bracketed guidance with actual values from the Ticket Data below. Do NOT print the guidance itself.
- The final output MUST NOT contain any square brackets [], example text (e.g., ...), or placeholder wording.
- If a value is not available in the ticket data, output N/A without brackets.
- Do NOT make up customer names, ticket IDs, timestamps, or any other details not present in the provided data.

Incident Details:

• Incident Ticket #    : [ticket id]
• Customer Ref #       : [customer reference]
• SR / Circuit ID      : [service or circuit ids]
• Incident Reported Time : [creation timestamp in DD MMM YYYY HH:MM GMT]
• Incident Resolved Time : [resolution timestamp in DD MMM YYYY HH:MM GMT or N/A]
• Incident Duration    : [computed duration or Ongoing]
• Reported Impact Type : [Circuit Down | High Latency | Flapping | Packet Loss | Other]
• Service Details      : [service type]
• Reported By          : [reporting party]
• BDM                  : [name or N/A]
• RSM                  : [name or N/A]

Executive Summary
[1-3 sentences: what happened, who/what was impacted, restoration time. Clear customer language. No blame.]

Reason for Outage (RFO)
[1-4 sentences: concise reason. If cause involves partner/provider actions or scheduling windows, state factually. If not fully identified, use approved wording: Untraced — ... or No Fault Found — ...]

Resolution
[Brief, factual corrective action that restored service.]

Preventative Measures
[Preventative steps or process improvements, especially around notice/coordination/change handling.]

Event Timeline
Time (UTC) | Occurrence
DD MMM YYYY HH:MM GMT | [concise description]
DD MMM YYYY HH:MM GMT | [concise description]
DD MMM YYYY HH:MM GMT | [concise description]
DD MMM YYYY HH:MM GMT | [concise description]

IMPORTANT:
- Output MUST contain only the sections and fields defined above, nothing before or after
- Use UTC/GMT format strictly: "DD MMM YYYY HH:MM GMT" for all timestamps
- Keep content neutral, factual, and free of internal jargon and internal codes
- If a field is not available, use N/A (without brackets)
- The final output MUST NOT contain any square brackets [] or example text

Ticket Data:
{data}` ,

  rfo_report: `You are a Remedy incident analyst for RFO (Reason For Outage) report generation. Generate an RFO report in the following EXACT format:

**Sample RFO Report Template:**

**Name of Customer:** [Extract the customer name from the ticket data. If not available, use "N/A"]
**Incident Ticket No.:** [Use the ticket ID provided in the request]
**Outage Start Date/Time:** [Refers to the exact timestamp when the service disruption or degradation began. This is typically the moment the first impact was detected — via system alerts, monitoring tools, or user reports — indicating the service was no longer operating normally or within defined thresholds. If the exact time is unclear, provide the best estimate based on monitoring or logs. Use UTC for consistency and format as "DD MMM YYYY HH:MM GMT" (e.g., "23 Feb 2025 00:00 GMT").]
**Outage Resolve Date/Time:** [Refers to the exact timestamp when the service was restored to normal operation. This means the issue causing the disruption has been mitigated or resolved, and the system is confirmed to be stable and performing within acceptable parameters. This should reflect when restoration was verified by system, tool, or customer, not just when a fix was implemented. Include monitoring confirmation if applicable. Use UTC and format as "DD MMM YYYY HH:MM GMT" (e.g., "23 Feb 2025 02:00 GMT"). If not resolved, use "N/A".]
**Outage Duration:** [Calculate the duration between start and end times. Format as "X hours Y minutes" or "X days Y hours Z minutes". If not resolved, use "Ongoing"]
**Reported Symptoms:** [Extract the initial symptoms or issues reported by the customer from the ticket data. Look for description, summary, or initial notes. If not available, use "N/A"]
**Reason for Outage:** [Underlying issue that triggered the service disruption. Identify the primary technical, operational, human, or external factor responsible for the outage, based on available evidence or analysis. If the root cause cannot be fully identified, use approved language: "Untraced — The issue could not be traced or reproduced despite extensive monitoring and diagnostics. Network performance has remained stable since restoration." or "No Fault Found — No fault was identified during or after the incident. No alarms or anomalies were detected. Continuous monitoring has been maintained, but no definitive root cause was determined." Choose the most appropriate statement.]
**Corrective Action (Resolution):** [Analyze the ticket data to determine what action was taken to resolve the issue. Look for resolution steps, fixes applied, or corrective measures. If no clear resolution is found, use "The cross-connect cable is replaced or N/A"]

IMPORTANT: 
- Use the exact field names and format above
- Format ALL dates as "DD MMM YYYY HH:MM GMT" (e.g., "23 Feb 2025 00:00 GMT")
- Extract actual dates and times from the ticket data when available
- Calculate outage duration accurately from start and end times
- Analyze the ticket content to provide accurate cause and resolution information
- If the root cause is not identified, use approved wording: "Untraced — ..." or "No Fault Found — ..." (see Reason for Outage)
- For complex or sensitive RFOs (e.g., human error, EOL/aging equipment, known software bugs, erroneous terminations, finance-related issues, failure to notify customers of planned maintenance), post the draft in #rfo-escalations Slack for management review and approval (Manager level and up) before release
- After approval, release to the customer via normal communication channels and record the RFO in the corresponding Remedy ticket
- Do not add extra formatting or change the structure
- Focus on technical details and infrastructure-related causes

DO's:
- Validate and confirm any ambiguous or unclear information
- Ensure all facts are accurate and verifiable

DON'Ts:
- Do not use acronyms unless defined
- Do not use PCCWG internal POP codes; use data center name, city, or DC code
- Do not use technical jargon that may not be understood by non-technical stakeholders

Ticket Data:
{data}`
};

/**
 * Service to handle Redis caching operations
 */
class RedisService {
  constructor() {
    this.client = null;
    this.isConnected = false;
  }

  /**
   * Connects to Redis instance
   */
  async connect() {
    if (this.isConnected) return;

    try {
      this.client = redis.createClient({
        url: config.redis.url,
        socket: {
          connectTimeout: 5000,
          lazyConnect: true
        }
      });

      this.client.on('error', (err) => {
        console.error('Redis Client Error:', err);
        this.isConnected = false;
      });

      this.client.on('connect', () => {
        console.log('Connected to Redis');
        this.isConnected = true;
      });

      await this.client.connect();
    } catch (error) {
      console.error('Failed to connect to Redis:', error);
      this.isConnected = false;
    }
  }

  /**
   * Disconnects from Redis
   */
  async disconnect() {
    if (this.client && this.isConnected) {
      await this.client.quit();
      this.isConnected = false;
    }
  }

  /**
   * Generates cache key for ticket
   * @param {string} ticketId - The ticket ID
   * @returns {string} Cache key
   */
  _generateCacheKey(ticketId) {
    return `ticket:${ticketId}:redacted`;
  }

  /**
   * Gets cached redacted content for a ticket
   * @param {string} ticketId - The ticket ID
   * @returns {Promise<string|null>} Cached redacted content or null if not found
   */
  async getCachedRedactedContent(ticketId) {
    try {
      await this.connect();
      if (!this.isConnected) return null;

      const key = this._generateCacheKey(ticketId);
      const cachedContent = await this.client.get(key);
      
      if (cachedContent) {
        console.log(`[Ticket ${ticketId}] Found cached redacted content`);
        return cachedContent;
      }
      
      return null;
    } catch (error) {
      console.error(`[Ticket ${ticketId}] Error getting cached redacted content:`, error);
      return null;
    }
  }

  /**
   * Caches redacted content for a ticket
   * @param {string} ticketId - The ticket ID
   * @param {string} redactedContent - The redacted content to cache
   * @param {number} ttl - Time to live in seconds (default: from config or 10 minutes)
   */
  async cacheRedactedContent(ticketId, redactedContent, ttl = null) {
    try {
      await this.connect();
      if (!this.isConnected) return;

      const cacheTtl = ttl || config.redis.ttl || 600;
      const key = this._generateCacheKey(ticketId);
      await this.client.setEx(key, cacheTtl, redactedContent);
      console.log(`[Ticket ${ticketId}] Cached redacted content with TTL: ${cacheTtl}s`);
    } catch (error) {
      console.error(`[Ticket ${ticketId}] Error caching redacted content:`, error);
    }
  }

  /**
   * Invalidates cached redacted content for a ticket
   * @param {string} ticketId - The ticket ID
   */
  async invalidateCache(ticketId) {
    try {
      await this.connect();
      if (!this.isConnected) return;

      const key = this._generateCacheKey(ticketId);
      await this.client.del(key);
      console.log(`[Ticket ${ticketId}] Invalidated cached redacted content`);
    } catch (error) {
      console.error(`[Ticket ${ticketId}] Error invalidating cache:`, error);
    }
  }
}

/**
 * Service to handle DLP (Data Loss Prevention) operations
 */
class DLPService {
  constructor() {
    this.client = new DlpServiceClient();
    this.projectId = config.api.gcpProjectId;
  }

  /**
   * Creates DLP inspection request configuration
   * @param {string} content - Content to inspect
   * @returns {Object} DLP request configuration
   */
  _createInspectRequest(content) {
    return {
      parent: `projects/${this.projectId}`,
      item: { value: content },
      inspectConfig: {
        infoTypes: [
          { name: 'EMAIL_ADDRESS' },
          { name: 'PHONE_NUMBER' }
        ],
        includeQuote: true
      }
    };
  }

  /**
   * Sanitizes sensitive data in JSON
   * @param {Object} jsonInput - JSON data to sanitize
   * @returns {Promise<Object>} Sanitized JSON data
   */
  async sanitizeJson(jsonInput) {
    try {
      const jsonString = JSON.stringify(jsonInput, null, 2);

      const MAX_CHUNK_SIZE = 300000;
      const chunks = [];

      for (let i = 0; i < jsonString.length; i += MAX_CHUNK_SIZE) {
        chunks.push(jsonString.slice(i, i + MAX_CHUNK_SIZE));
      }

      // Process DLP chunks in parallel
      const redactedChunks = await Promise.all(chunks.map(async (chunk) => {
        const [response] = await this.client.inspectContent(
          this._createInspectRequest(chunk)
        );
        const findings = response.result.findings || [];
        let redactedChunk = chunk;
        for (const finding of findings) {
          if (finding.quote) {
            const escaped = finding.quote.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
            redactedChunk = redactedChunk.replace(new RegExp(escaped, 'g'), '***REDACTED***');
          }
        }
        return redactedChunk;
      }));
      let redactedString = redactedChunks.join('');

      // Clean up and format the redacted content
      const sanitizedContent = redactedString
        .replace(/[^\x00-\x7F]+/g, '') // Remove non-ASCII characters
        .replace(/\\\\\*\*/g, '\\n**'); // Fix markdown formatting

      return sanitizedContent;

    } catch (error) {
      console.error('DLP sanitization error:', error);
      throw new Error(`Failed to sanitize sensitive data: ${error.message}`);
    }
  }
}

/**
 * Service to handle Helix API operations
 */
class HelixApiService {
  /**
   * Creates request options for the Helix API
   * @param {string} ticketId - The ticket ID
   * @param {string} token - The authorization token
   * @returns {Object} The request options
   */
  static _createRequestOptions(ticketId, token) {
    return {
      url: `https://${config.api.hostName}/cs-helix-ticketing/internalHelix/troubleTicket/${ticketId}`,
      method: 'GET',
      headers: {
        'Host': config.api.hostHeader,
        'Authorization': `Bearer ${token}`
      },
      timeout: 30000 // 30 seconds timeout
    };
  }

  /**
   * Makes an HTTPS request
   * @param {Object} options - The request options
   * @param {Object} body - Optional request body (for POST/PUT requests)
   * @returns {Promise<Object>} The response data
   */
  static async _makeRequest(options, body = null) {
    const maxRetries = 3;
    const maxTotalWait = 30000; // 30 seconds
    let attempt = 0;
    let lastError;
    let totalWait = 0;
    while (attempt < maxRetries && totalWait < maxTotalWait) {
      try {
        const url = new URL(options.url);
        const httpsOptions = {
          hostname: url.hostname,
          port: url.port || 443,
          path: url.pathname + url.search,
          method: options.method,
          headers: options.headers,
          timeout: options.timeout || 30000
        };
        return await this._makeHttpsRequest(httpsOptions, body);
      } catch (error) {
        lastError = error;
        attempt++;
        if (attempt < maxRetries) {
          const delay = 500 * Math.pow(2, attempt); // 1s, 2s, 4s
          totalWait += delay;
          if (totalWait >= maxTotalWait) break;
          console.warn(`HelixApiService._makeRequest attempt ${attempt} failed: ${error.message}. Retrying in ${delay}ms...`);
          await new Promise(res => setTimeout(res, delay));
        }
      }
    }
    throw new Error(`HelixApiService._makeRequest failed after ${attempt} attempts and ${totalWait}ms: ${lastError.message}`);
  }

  /**
   * Makes an HTTPS request using the native https module
   * @param {Object} options - The request options
   * @param {Object} body - Optional request body (for POST/PUT requests)
   * @returns {Promise<Object>} The response data
   */
  static _makeHttpsRequest(options, body = null) {
    return new Promise((resolve, reject) => {
      const req = https.request(options, (res) => {
        let data = '';
        
        res.on('data', (chunk) => {
          data += chunk;
        });
        
        res.on('end', () => {
          try {
            if (res.statusCode >= 200 && res.statusCode < 300) {
              const jsonData = JSON.parse(data);
              resolve(jsonData);
            } else {
              reject(new Error(`API request failed with status ${res.statusCode}: ${data}`));
            }
          } catch (error) {
            reject(new Error(`Failed to parse response: ${error.message}`));
          }
        });
      });

      req.on('error', (error) => {
        reject(new Error(`Network request failed: ${error.message}`));
      });
      
      if (body) {
        req.write(JSON.stringify(body));
      }
      
      req.end();
    });
  }

  /**
   * Gets ticket details by ID
   * @param {string} ticketId - The ID of the ticket to retrieve
   * @returns {Promise<Object>} The ticket data
   */
  static async getTicketById(ticketId) {
    if (!ticketId) {
      throw new Error('Ticket ID is required');
    }

    try {
      const token = await AuthService.getToken();
      const options = this._createRequestOptions(ticketId, token);
      return await this._makeRequest(options);
    } catch (error) {
      console.error('Failed to retrieve ticket:', error);
      throw new Error(`Failed to retrieve ticket details: ${error.message}`);
    }
  }

  /**
   * Creates a new ticket via Helix API using axios (consistent with auth.js)
   * @param {Object} ticketPayload - The ticket creation payload
   * @returns {Promise<Object>} The created ticket data
   */
  static async createTicket(ticketPayload) {
    if (!ticketPayload) {
      throw new Error('Ticket payload is required');
    }

    try {
      const token = await AuthService.getToken();
      const url = `https://${config.api.hostName}/cs-helix-ticketing/internalHelix/troubleTicket`;
      
      const response = await axios.post(url, ticketPayload, {
        headers: {
          'Host': config.api.hostHeader,
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        timeout: 30000 // 30 seconds timeout
      });

      return response.data;
    } catch (error) {
      console.error('Failed to create ticket:', error);
      if (error.response) {
        throw new Error(`Failed to create ticket: ${error.response.status} ${error.response.statusText} - ${JSON.stringify(error.response.data)}`);
      } else if (error.request) {
        throw new Error(`Failed to create ticket: No response received from server - ${error.message}`);
      } else {
        throw new Error(`Failed to create ticket: ${error.message}`);
      }
    }
  }
}

// Initialize services
const dlpService = new DLPService();
const vertexAI = new VertexAI({ project: config.api.gcpProjectId, location: config.vertexAi.location });
const model = vertexAI.getGenerativeModel({ model: config.vertexAi.model, generationConfig: { temperature: parseFloat(config.vertexAi.temperature) } });
const redisService = new RedisService();

/**
 * Cloud Function to retrieve and sanitize ticket details
 * @param {Object} req - The HTTP request object
 * @param {Object} res - The HTTP response object
 */
functions.http('remedyApiForWebhook', async (req, res) => {
  const startTime = Date.now();
  
  // Log the incoming request body
  console.log('Received req.body:', JSON.stringify(req.body, null, 2));

  try {
    if (req.method !== 'POST') {
      return res.status(405).json({ 
        success: false,
        error: 'Method not allowed', 
        message: 'Only POST requests are accepted',
        timestamp: new Date().toISOString()
      });
    }

    // Validate request
    const validationErrors = validateRequest(req.body);
    if (validationErrors.length > 0) {
      return res.status(400).json({
        success: false,
        error: 'Validation failed',
        details: validationErrors,
        timestamp: new Date().toISOString()
      });
    }

    // Handle ticket creation intent
    // Note: ticketId is optional for ticket_creation (can be empty/null/undefined) and is not used
    if (req.body.intent === 'ticket_creation') {
      try {
        const createdTicket = await HelixApiService.createTicket(req.body.ticketCreationPayload);
        return res.status(200).json({
          success: true,
          ticketCreationResponse: createdTicket, // Full Helix API response including all fields
          metadata: {
            processingTime: Date.now() - startTime,
            timestamp: new Date().toISOString()
          }
        });
      } catch (error) {
        console.error('Error creating ticket:', error);
        return res.status(500).json({
          success: false,
          error: true,
          message: error.message,
          timestamp: new Date().toISOString(),
          errorType: error.name,
          suggestions: getErrorSuggestions(error),
          webhookCompatible: true
        });
      }
    }

    // Check cache first for redacted content
    const cachedRedactedContent = await redisService.getCachedRedactedContent(req.body.ticketId);
    let sanitizedContent;

    if (cachedRedactedContent) {
      console.log(`[Ticket ${req.body.ticketId}] Using cached redacted content, skipping DLP processing`);
      
      // Check if cached content indicates IT helpdesk ticket
      try {
        const cachedData = JSON.parse(cachedRedactedContent);
        if (isITHelpdeskTicket(cachedData)) {
          console.log(`[Ticket ${req.body.ticketId}] Cached content indicates IT helpdesk ticket - blocking information disclosure`);
          return res.status(200).json({
            success: false,
            error: 'IT Helpdesk Ticket',
            message: 'This is an IT helpdesk ticket and we are not supposed to provide information about it',
            ticketId: req.body.ticketId,
            timestamp: new Date().toISOString()
          });
        }
      } catch (parseError) {
        // If we can't parse cached content, continue with normal processing
        console.warn(`[Ticket ${req.body.ticketId}] Could not parse cached content for IT helpdesk check: ${parseError.message}`);
      }
      
      sanitizedContent = cachedRedactedContent;
    } else {
      console.log(`[Ticket ${req.body.ticketId}] No cached redacted content found, processing with DLP`);
      
      const ticketData = await HelixApiService.getTicketById(req.body.ticketId);

      // Check if this is an IT helpdesk ticket
      if (isITHelpdeskTicket(ticketData)) {
        console.log(`[Ticket ${req.body.ticketId}] Detected IT helpdesk ticket - blocking information disclosure`);
        return res.status(200).json({
          success: false,
          error: 'IT Helpdesk Ticket',
          message: 'This is an IT helpdesk ticket and we are not supposed to provide information about it',
          ticketId: req.body.ticketId,
          timestamp: new Date().toISOString()
        });
      }

      // Process email notes in parallel before DLP sanitization
      if (Array.isArray(ticketData.notes)) {
        ticketData.notes = await Promise.all(ticketData.notes.map(async (note) => {
          if (note.id && note.id.includes('(Email)') && note.text) {
            console.log(`[Ticket ${req.body.ticketId}] Reducing email thread content for note ID: ${note.id}`);
            note.text = getInitialMessage(note.text);
            console.log(`[Ticket ${req.body.ticketId}] Content of note ID: ${note.id} after email reduction: ${note.text}`);
          }
          return note;
        }));
      }

      const jsonString = JSON.stringify(ticketData);
      const estimatedTokens = Math.ceil(jsonString.length / 2);
      console.log(`[Ticket ${req.body.ticketId}] Estimated tokens after email reduction: ${estimatedTokens}`);

      // If token size is still too large after email reduction, summarize individual large notes
      if (estimatedTokens > 900000 && Array.isArray(ticketData.notes)) {
        console.log(`[Ticket ${req.body.ticketId}] Further processing large content. Total notes: ${ticketData.notes.length}`);
        let summarizedCount = 0;
        ticketData.notes = await Promise.all(ticketData.notes.map(async (note) => {
          if (note.text?.length > 30000) {
            console.log(`[Ticket ${req.body.ticketId}] Summarizing note ID: ${note.id} with length: ${note.text.length} characters. Content: ${note.text}`);
            const summaryResult = await model.generateContent({
              contents: [{ role: 'user', parts: [{ text: `Summarize this note briefly:\r\n\r\n${note.text}` }] }],
              generationConfig: { temperature: 0.0 } // Set temperature to 0.0 for note summarization
            });
            note.text = summaryResult.response.candidates[0]?.content?.parts[0]?.text || note.text;
            console.log(`[Ticket ${req.body.ticketId}] Summarized note length: ${note.text.length} characters`);
            summarizedCount++;
          }
          return note;
        }));
        console.log(`[Ticket ${req.body.ticketId}] Total notes summarized by Vertex AI: ${summarizedCount} out of ${ticketData.notes.length}`);
      }

      sanitizedContent = await dlpService.sanitizeJson(ticketData);
      
      // Cache the redacted content for future use
      await redisService.cacheRedactedContent(req.body.ticketId, sanitizedContent);
      console.log(`[Ticket ${req.body.ticketId}] Cached redacted content for future requests`);
    }

    console.log(`[Ticket ${req.body.ticketId}] Sanitized content length: ${sanitizedContent.length} characters`);
    console.log(`[Ticket ${req.body.ticketId}] Sanitized content size: ${Buffer.from(sanitizedContent).length / 1024} KB`);

    const userIntent = req.body?.intent || 'detailed';
    const customPrompt = req.body?.prompt;

    let prompt;
    if (userIntent === 'custom' && customPrompt) {
      // Use webhook-optimized custom prompt
      console.log(`[Ticket ${req.body.ticketId}] Using custom prompt: ${customPrompt}`);
      prompt = WEBHOOK_PROMPT_TEMPLATES.custom
        .replace('{question}', customPrompt)
        .replace('{ticketId}', req.body.ticketId)
        .replace('{data}', sanitizedContent);
    } else if (userIntent === 'summary') {
      // Explicitly use summary template
      prompt = WEBHOOK_PROMPT_TEMPLATES.summary
        .replace('{ticketId}', req.body.ticketId)
        .replace('{data}', sanitizedContent);
    } else {
      // Use webhook-optimized default prompts for the intent
      const promptTemplate = WEBHOOK_PROMPT_TEMPLATES[userIntent] || WEBHOOK_PROMPT_TEMPLATES.detailed;
      prompt = promptTemplate
        .replace('{ticketId}', req.body.ticketId)
        .replace('{data}', sanitizedContent);
    }

    const result = await model.generateContent({
      contents: [{ role: 'user', parts: [{ text: prompt }] }]
    });

    const summary = result.response.candidates[0]?.content?.parts[0]?.text;

    // Enforce word count for different intents
    if (userIntent === 'summary' || userIntent === 'detailed') {
      const wordCount = summary ? summary.trim().split(/\s+/).length : 0;
      if (wordCount < 1000 || wordCount > 3000) {
        console.warn(`Summary word count out of range: ${wordCount} words (should be 1000-3000)`);
      }
    } else if (userIntent === 'rfo_report') {
      const wordCount = summary ? summary.trim().split(/\s+/).length : 0;
      if (wordCount < 50 || wordCount > 500) {
        console.warn(`RFO report word count out of range: ${wordCount} words (should be 50-500)`);
      }
    }

    // ✅ FIXED: Return structured JSON instead of JSON string
    return res.status(200).json({
      success: true,
      ticketId: req.body.ticketId,
      summary: summary?.trim() || 'No summary generated.',
      cached: !!cachedRedactedContent,
      customPrompt: customPrompt || null,
      intent: customPrompt ? 'custom' : userIntent,
      metadata: {
        processingTime: Date.now() - startTime,
        contentLength: sanitizedContent.length,
        vertexAIModel: 'gemini-2.5-flash',
        cacheHit: !!cachedRedactedContent,
        dataSource: 'helix-api',
        sanitized: true,
        timestamp: new Date().toISOString()
      }
    });
    
  } catch (error) {
    console.error('Error in ticketAgent function:', error);
    
    // ✅ ENHANCED: Better error handling for webhook
    const errorResponse = {
      success: false,
      error: true,
      message: error.message,
      ticketId: req.body?.ticketId,
      timestamp: new Date().toISOString(),
      errorType: error.name,
      suggestions: getErrorSuggestions(error),
      webhookCompatible: true
    };
    
    return res.status(500).json(errorResponse);
  } finally {
    // Clean up Redis connection
    await redisService.disconnect();
  }
});