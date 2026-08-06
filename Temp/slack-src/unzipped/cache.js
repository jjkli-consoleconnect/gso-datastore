const redis = require('redis');
const { promisify } = require('util');

const REDIS_URL = process.env.REDIS_URL || 'redis://localhost:6379';
const client = redis.createClient({ url: REDIS_URL });

client.connect();

// Set session with optional TTL (in seconds)
async function setSession(sessionId, data, ttlSeconds = null) {
  if (ttlSeconds) {
    await client.set(sessionId, JSON.stringify(data), { EX: ttlSeconds });
  } else {
    await client.set(sessionId, JSON.stringify(data));
  }
}

// Get session by sessionId
async function getSession(sessionId) {
  const data = await client.get(sessionId);
  return data ? JSON.parse(data) : null;
}

// Delete session
async function deleteSession(sessionId) {
  await client.del(sessionId);
}

// Efficient per-user activity tracking with 10-minute TTL
async function updateUserActivity(userId, { isDM, channel }) {
  const activityKey = `slack-${userId}-${isDM ? 'dm' : channel}-activity`;
  await client.set(activityKey, Date.now(), { EX: 600 }); // 10 minutes TTL
}

// Check if user session should be refreshed (activity key exists = user is active)
async function shouldRefreshSession(userId, { isDM, channel }) {
  const activityKey = `slack-${userId}-${isDM ? 'dm' : channel}-activity`;
  const activityExists = await client.exists(activityKey);
  return activityExists === 1;
}

// Check if user session should be purged (no activity key = user is idle)
async function shouldPurgeSession(userId, { isDM, channel }) {
  const activityKey = `slack-${userId}-${isDM ? 'dm' : channel}-activity`;
  const activityExists = await client.exists(activityKey);
  return activityExists === 0;
}

// Purge specific user session if idle
async function purgeUserSession(userId, { isDM, channel }) {
  if (await shouldPurgeSession(userId, { isDM, channel })) {
    const cacheKey = getCacheKey(userId, { isDM, channel });
    await deleteSession(cacheKey);
    console.log(`Purged idle session for user ${userId} (${isDM ? 'DM' : 'thread'})`);
    return true;
  }
  return false;
}

// Get session with automatic idle checking and purging
async function getSessionWithIdleCheck(userId, { isDM, channel }) {
  // First check if we should purge the session due to inactivity
  await purgeUserSession(userId, { isDM, channel });
  
  // Then get the session (which might be null if purged)
  const cacheKey = getCacheKey(userId, { isDM, channel });
  return await getSession(cacheKey);
}

// Set session with activity tracking
async function setSessionWithActivity(userId, { isDM, channel }, data, ttlSeconds = null) {
  const cacheKey = getCacheKey(userId, { isDM, channel });
  await setSession(cacheKey, data, ttlSeconds);
  await updateUserActivity(userId, { isDM, channel });
}

// Flush specific user sessions
async function flushUserSessions(userId, { isDM, channel }) {
  try {
    const cacheKey = getCacheKey(userId, { isDM, channel });
    const activityKey = `slack-${userId}-${isDM ? 'dm' : channel}-activity`;
    
    await deleteSession(cacheKey);
    await client.del(activityKey);
    
    console.log(`Flushed sessions for user ${userId} (${isDM ? 'DM' : 'thread'})`);
    return true;
  } catch (error) {
    console.error('Error flushing user sessions:', error);
    return false;
  }
}

// Flush all sessions (existing function)
async function flushAllSessions() {
  try {
    const keys = await client.keys('slack-*');
    if (keys.length > 0) {
      await client.del(keys);
      console.log(`Flushed ${keys.length} sessions`);
    }
    return keys.length;
  } catch (error) {
    console.error('Error flushing sessions:', error);
    return 0;
  }
}

// Generate sessionId based on userId, DM/thread, and time window
function getSessionIdTimeBased(userId, { isDM, channel }, windowMinutes = 15) {
  const thread = isDM ? 'dm' : channel;
  const now = Date.now();
  const timeSlice = Math.floor(now / (1000 * 60 * windowMinutes));
  return `slack-${userId}-${thread}-${timeSlice}`;
}

// Generate cache key based on userId and DM/thread (no time window)
function getCacheKey(userId, { isDM, channel }) {
  const thread = isDM ? 'dm' : channel;
  return `slack-${userId}-${thread}`;
}

module.exports = {
  setSession,
  getSession,
  deleteSession,
  updateUserActivity,
  shouldRefreshSession,
  shouldPurgeSession,
  purgeUserSession,
  getSessionWithIdleCheck,
  setSessionWithActivity,
  flushUserSessions,
  flushAllSessions,
  getSessionIdTimeBased, // For ADK sessionId
  getCacheKey,           // For Redis cache key
};