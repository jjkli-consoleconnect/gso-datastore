const { Firestore } = require('@google-cloud/firestore');
const axios = require('axios');
const { GoogleAuth } = require('google-auth-library');

const COLLECTION = process.env.MAPPING_COLLECTION || 'gmailDispatcher_mappings';

const firestore = new Firestore();
const auth = new GoogleAuth();

/**
 * Cloud Function triggered by Pub/Sub (gmail-watch-topic).
 * Reads mappings from Firestore and forwards Gmail notifications
 * to configured Apps Script webhooks. Attempts to obtain an OIDC ID
 * token for the target webhook URL and attach it as Authorization.
 */
exports.gmailDispatcher = async (pubSubEvent) => {
  try {
    const raw = pubSubEvent.data ? Buffer.from(pubSubEvent.data, 'base64').toString() : null;
    let notification = {};
    if (raw) {
      try { notification = JSON.parse(raw); } catch (e) { notification = { raw }; }
    }

    const labelCandidates = new Set();
    if (notification.messages) {
      notification.messages.forEach(m => {
        if (m.labelIds) (m.labelIds || []).forEach(l => labelCandidates.add(l));
        if (m.message && m.message.labelIds) (m.message.labelIds || []).forEach(l => labelCandidates.add(l));
      });
    }
    if (notification.labels) (notification.labels || []).forEach(l => labelCandidates.add(l));

    const mappingsSnap = await firestore.collection(COLLECTION).get();
    if (mappingsSnap.empty) { console.log('No mappings found in Firestore collection:', COLLECTION); return; }

    const results = await Promise.all(mappingsSnap.docs.map(async doc => {
      const map = doc.data();
      const webhookUrl = map.webhookUrl;
      if (!webhookUrl) return { id: doc.id, ok: false, reason: 'no webhookUrl' };

      const shouldForward = (map.wildcard === true) || (
        Array.isArray(map.labels) && map.labels.some(lbl => labelCandidates.has(lbl) || labelCandidates.has(String(lbl).toUpperCase()) || labelCandidates.has(String(lbl).toLowerCase()))
      );
      if (!shouldForward) return { id: doc.id, ok: false, reason: 'no label match' };

      try {
        const headers = { 'content-type': 'application/json' };
        try {
          const client = await auth.getIdTokenClient(webhookUrl);
          const authHeaders = await client.getRequestHeaders();
          if (authHeaders && authHeaders.authorization) headers.authorization = authHeaders.authorization;
        } catch (tokenErr) {
          console.warn('Could not obtain ID token for webhook', doc.id, tokenErr && tokenErr.message);
        }

        const body = { notification, dispatcherSecret: map.secret || null };
        await axios.post(webhookUrl, body, { headers, timeout: 20000 });
        return { id: doc.id, ok: true };
      } catch (err) {
        console.error('Forward error for mapping', doc.id, err && err.message);
        return { id: doc.id, ok: false, reason: err && err.message };
      }
    }));

    console.log('Dispatch results:', results);
  } catch (err) {
    console.error('Unhandled error in gmailDispatcher:', err && err.stack || err);
    throw err;
  }
};
