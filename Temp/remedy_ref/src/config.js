const config = {
    auth: {
      url: process.env.AUTH_URL,
      clientId: process.env.HELIX_AUTH0_CLIENT_ID,
      clientSecret: process.env.HELIX_AUTH0_CLIENT_SECRET,
      grantType: 'client_credentials',
      audience: process.env.AUDIENCE
    },
    api: {
      hostName: process.env.HOST_NAME,
      hostHeader: process.env.HOST_HEADER,
      gcpProjectId: process.env.GCP_PROJECT_ID
    },
    redis: {
      url: process.env.REDIS_URL,
      ttl: parseInt(process.env.REDIS_TTL) || 600 // Default 10 minutes
    },
    vertexAi: {
      location: process.env.VERTEX_AI_LOCATION,
      temperature: process.env.VERTEX_AI_TEMPERATURE,
      model: process.env.VERTEX_AI_MODEL
    }
  };
  
  module.exports = config; 