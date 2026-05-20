const config = require('./config');
const axios = require('axios');
const { URL } = require('url');

/**
 * Service to handle authentication with the Console Connect API
 */
class AuthService {
  /**
   * Get an access token for API authentication
   * @returns {Promise<string>} The access token
   * @throws {Error} If token retrieval fails
   */
  static async getToken() {    
    const body = {
      client_id: config.auth.clientId,
      client_secret: config.auth.clientSecret,
      grant_type: config.auth.grantType,
      audience: config.auth.audience,
    };

    try {
      const response = await axios.post(
        config.auth.url,
        new URLSearchParams(body).toString(),
        {
          headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
          },
        }
      );

      const data = response.data;
      
      if (!data.access_token) {
        console.error('No access token in response:', data);
        throw new Error('No access token received from authentication service');
      }
      
      console.log('Access token received successfully');
      return data.access_token;
    } catch (error) {
      console.error('Authentication error:', error);
      
      // Provide more specific error messages for webhook debugging
      if (error.message.includes('network') || error.message.includes('connection')) {
        throw new Error('Network error during authentication - check connectivity');
      } else if (error.message.includes('authentication failed')) {
        throw new Error(`Authentication service error: ${error.message}`);
      } else {
        throw new Error(`Authentication failed: ${error.message}`);
      }
    }
    
  }
}

module.exports = AuthService; 