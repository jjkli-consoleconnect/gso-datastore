module.exports = {
  SLACK_SIGNING_SECRET: process.env.SLACK_SIGNING_SECRET,
  SLACK_BOT_TOKEN: process.env.SLACK_BOT_TOKEN,
  ADK_API_URL: process.env.ADK_API_URL,
  BOT_USER_ID: process.env.BOT_USER_ID,
  REDIS_URL: process.env.REDIS_URL,
  FLUSH_SECRET: process.env.FLUSH_SECRET,
  // Dialogflow configuration for external conversational agent
  DIALOGFLOW: {
    PROJECT_ID: process.env.DIALOGFLOW_PROJECT_ID,
    LOCATION: process.env.DIALOGFLOW_LOCATION,
    AGENT_ID: process.env.DIALOGFLOW_AGENT_ID
  },
  SLACK_DISCLAIMER: process.env.SLACK_DISCLAIMER,
  // BigQuery table for training data verification (e.g. pccw-internal-virtual-agent.wanda_ds.TrainingData)
  TRAINING_DATA_TABLE: process.env.TRAINING_DATA_TABLE,
  // Helix Remedy user validation (Auth0 + user check by loginId)
  AUTH_URL: process.env.AUTH_URL,
  HELIX_AUTH0_CLIENT_ID: process.env.HELIX_AUTH0_CLIENT_ID,
  HELIX_AUTH0_CLIENT_SECRET: process.env.HELIX_AUTH0_CLIENT_SECRET,
  AUDIENCE: process.env.AUDIENCE,
  HOST_NAME: process.env.HOST_NAME,
  HOST_HEADER: process.env.HOST_HEADER,
};