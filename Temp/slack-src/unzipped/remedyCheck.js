/**
 * Remedy user verification via Helix API.
 * Required when the user prompt contains a Helix Remedy incident ID (INC + 12 digits).
 * loginId = Slack email local-part (e.g. pbertol from pbertol@consoleconnect.com).
 */
const axios = require('axios');
const config = require('./config');

const REMEDY_INCIDENT_PATTERN = /\bINC\d{12}\b/i;

const REMEDY_ACCESS_DENIED_MESSAGE =
  'I believe you do not have access permissions to the Helix Remedy system to extract Remedy tickets. Should you need system access, please raise a CSCM request to apply for access permissions.';

/** In-memory Auth0 token cache */
let cachedToken = null;
let cachedTokenExpiresAt = 0;

/**
 * @param {string} text - User message text
 * @returns {boolean}
 */
function hasRemedyIncidentId(text) {
  return REMEDY_INCIDENT_PATTERN.test(String(text || ''));
}

/**
 * Extract Helix loginId from Slack email (part before @).
 * @param {string} userEmail
 * @returns {string}
 */
function getLoginIdFromEmail(userEmail) {
  const trimmedEmail = userEmail && typeof userEmail === 'string' ? userEmail.trim().toLowerCase() : '';
  if (!trimmedEmail || !trimmedEmail.includes('@')) return '';
  return trimmedEmail.split('@')[0] || '';
}

/**
 * Get Auth0 client-credentials access token (cached until near expiry).
 * @returns {Promise<string>}
 */
async function getHelixAccessToken() {
  const now = Date.now();
  if (cachedToken && now < cachedTokenExpiresAt) {
    console.log('[Remedy] Using cached Helix access token');
    return cachedToken;
  }

  const { AUTH_URL, HELIX_AUTH0_CLIENT_ID, HELIX_AUTH0_CLIENT_SECRET, AUDIENCE } = config;

  if (!AUTH_URL || !HELIX_AUTH0_CLIENT_ID || !HELIX_AUTH0_CLIENT_SECRET || !AUDIENCE) {
    throw new Error(
      'Missing Helix auth config (AUTH_URL, HELIX_AUTH0_CLIENT_ID, HELIX_AUTH0_CLIENT_SECRET, AUDIENCE)',
    );
  }

  console.log('[Remedy] Requesting Helix access token from AUTH_URL');
  const { data } = await axios.post(
    AUTH_URL,
    {
      client_id: HELIX_AUTH0_CLIENT_ID,
      client_secret: HELIX_AUTH0_CLIENT_SECRET,
      grant_type: 'client_credentials',
      audience: AUDIENCE,
    },
    { headers: { 'Content-Type': 'application/json' } },
  );

  const accessToken = data && data.access_token;
  if (!accessToken) {
    throw new Error('Helix auth response missing access_token');
  }

  const expiresInSec = typeof data.expires_in === 'number' ? data.expires_in : 3600;
  // Refresh 60s before expiry
  cachedToken = accessToken;
  cachedTokenExpiresAt = now + Math.max(expiresInSec - 60, 60) * 1000;

  console.log('[Remedy] Helix access token acquired', {
    tokenType: data.token_type || 'Bearer',
    expiresIn: expiresInSec,
  });

  return accessToken;
}

/**
 * Validate Helix Remedy user by loginId.
 * @param {string} loginId
 * @returns {Promise<{allowed: boolean, error?: string}>}
 */
async function validateHelixUser(loginId) {
  const hostName = config.HOST_NAME;
  const hostHeader = config.HOST_HEADER;
  if (!hostName || !hostHeader) {
    console.warn(
      'HOST_NAME / HOST_HEADER not set - skipping Remedy verification (allowing access)',
    );
    return { allowed: true };
  }

  const token = await getHelixAccessToken();
  const url = `https://${hostName}/cs-helix-ticketing/internalHelix/getUserProfileStatus/${encodeURIComponent(loginId)}`;

  console.log('[Remedy] Calling Helix user validation API', {
    method: 'GET',
    url,
    loginId,
    hostHeader,
  });

  try {
    const response = await axios.get(url, {
      headers: {
        Host: hostHeader,
        Authorization: `Bearer ${token}`,
      },
      timeout: 30000, // 30 seconds
      validateStatus: () => true,
    });

    const data = response.data || {};
    const profileStatus = data['Profile Status'];

    console.log('[Remedy] Helix user validation API response:', {
      loginId,
      status: response.status,
      data,
    });

    // Verified: HTTP 200 + { "Profile Status": "Enabled" }
    if (response.status === 200 && profileStatus === 'Enabled') {
      console.log('[Remedy] Helix user validation allowed:', { loginId, status: response.status });
      return { allowed: true };
    }

    // Not verified: HTTP 400 + { "error": { code, title, detail } }
    console.log('[Remedy] Helix user validation denied:', {
      loginId,
      status: response.status,
      profileStatus: profileStatus || null,
      error: data.error || null,
    });
    return { allowed: false };
  } catch (error) {
    console.error('Helix user validation request error:', error.message);
    return { allowed: false, error: error.message };
  }
}

/**
 * Check if a user has Helix Remedy access using Slack email local-part as loginId.
 * @param {string} userEmail - Slack user email
 * @param {string} [_userName] - Unused; kept for call-site compatibility
 * @returns {Promise<{allowed: boolean, error?: string}>}
 */
async function hasRemedyAccess(userEmail, _userName) {
  const loginId = getLoginIdFromEmail(userEmail);

  console.log('[Remedy] Derived loginId from Slack email:', {
    email: userEmail || '(empty)',
    loginId: loginId || '(empty)',
  });

  if (!loginId) {
    console.warn('No valid email/loginId provided for Remedy Helix check');
    return { allowed: false };
  }

  if (!config.HOST_NAME || !config.HOST_HEADER) {
    console.warn(
      'HOST_NAME / HOST_HEADER not set - skipping Remedy verification (allowing access)',
    );
    return { allowed: true };
  }

  try {
    return await validateHelixUser(loginId);
  } catch (error) {
    console.error('Remedy Helix verification error:', error.message);
    return { allowed: false, error: error.message };
  }
}

module.exports = {
  hasRemedyIncidentId,
  hasRemedyAccess,
  getLoginIdFromEmail,
  REMEDY_ACCESS_DENIED_MESSAGE,
  REMEDY_INCIDENT_PATTERN,
};
