/**
 * Configuration constants for Cable Outage Tracker
 */

const CONFIG = {
  // Feature flags
  FEATURES: {
    // Review Queue workflow (derived tab + reviewer edits).
    REVIEW_QUEUE_ENABLED: true
  },

  // Cloud Run Service
  CLOUD_RUN_BASE_URL: 'https://gmail-sheet-proxy-14417857267.europe-west2.run.app',
  MAX_MESSAGE_IDS: 500,
  MAX_BODY_LENGTH: 10000,
  
  // Sheet Names
  SHEETS: {
    EMAIL_DETAILS: '[Email Details]',
    REVIEW_QUEUE: '[Review Queue]'
  },
  
  // Column Indices (1-based)
  COLUMNS: {
    // [Email Details] sheet columns
    EMAIL_DETAILS: {
      EMAIL_ID: 1,    // A
      SUBJECT: 2,     // B
      SENDER: 3,      // C
      BODY: 4         // D
    },
    
    // Outage tracking sheets columns (all other sheets + Review Queue)
    OUTAGE: {
      // Canonical "system-tab" schema (and [Review Queue])
      // System	FailedDate	FailedTime	ResumedDate	ResumedTime	RepairedDate	RepairedTime	Segment	Reason	Event Type	RecoveryProgress	Service Impact	NoOfCircuits	NoNonRestored	RemedyTicket	ReviewStatus	OutageID	EmailID	EmailDateTime	RowAddedAt	LastUpdatedAt
      SYSTEM: 1,                // A
      FAILED_DATE: 2,           // B
      FAILED_TIME: 3,           // C
      RESUMED_DATE: 4,          // D
      RESUMED_TIME: 5,          // E
      REPAIRED_DATE: 6,         // F
      REPAIRED_TIME: 7,         // G
      SEGMENT: 8,               // H
      REASON: 9,                // I
      EVENT_TYPE: 10,           // J
      RECOVERY_PROGRESS: 11,    // K
      SERVICE_IMPACT: 12,       // L
      NO_OF_CIRCUITS: 13,       // M
      NO_NON_RESTORED: 14,      // N
      REMEDY_TICKET: 15,        // O
      REVIEW_STATUS: 16,        // P
      // OutageID is optional in Sheets; the backend can derive it deterministically
      // from System+Segment+FailedDate when missing.
      OUTAGE_ID: 17,            // Q
      EMAIL_ID: 18,             // R
      // Kept as EMAIL_TIMESTAMP for compatibility with existing Apps Script code.
      EMAIL_TIMESTAMP: 19,      // S (EmailDateTime)
      ROW_ADDED_AT: 20,         // T
      LAST_UPDATED_AT: 21,      // U
      TOTAL_COLUMNS: 21         // Total columns in outage sheets (A-U).
    }
  },
  
  // Review Status Options
  REVIEW_STATUS: {
    APPROVED: 'Approved',
    MODIFIED: 'Modified',
    REJECTED: 'Rejected',
    AUTO_SYNCED: 'Auto-Synced',
    PENDING: 'Pending'
  },
  
  // Messages
  MESSAGES: {
    NO_IDS_FOUND: 'No message IDs found in either sheet.',
    EMAIL_NOT_FOUND: 'EMAIL NOT FOUND',
    TRUNCATED_SUFFIX: '... (truncated)'
  },
  
  // Review Settings
  REVIEW: {
    SHOW_ALL: true,
    AUTO_REMOVE_REVIEWED: true
  },

  // Audit logging configuration
  AUDIT: {
    // Audits per-cell edits on system sheets.
    // Baseline is stored in an append-only _AuditShadow snapshot (created from all system sheets).
    ENABLED: true,
    // Legacy: no longer tied to a specific sheet name.
    SHEET_NAME: '[Review Queue]',
    SHADOW_SHEET_NAME: '_AuditShadow',
    ENDPOINT: '',  // Will use CLOUD_RUN_BASE_URL + '/audit/review_edits'
    BATCH_SIZE: 100,
    FLUSH_INTERVAL_SECONDS: 60
  }
};

// Sheets to exclude from processing
const EXCLUDED_SHEETS = [
  CONFIG.SHEETS.EMAIL_DETAILS,
  CONFIG.SHEETS.REVIEW_QUEUE,
  CONFIG.AUDIT.SHADOW_SHEET_NAME
];
