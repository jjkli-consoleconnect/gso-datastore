const { WebClient } = require('@slack/web-api')
const config = require('./config');

const slackClient = new WebClient(config.SLACK_BOT_TOKEN)

const feedbackButtons = async (sessionID, responseId, channelId, userId, ts = null) => {
   try {
    let slackMsg = {
      channel: channelId,
      text: `${sessionID} ${responseId} ${userId}`,
      blocks: [
        {
          type: "actions",
          elements: [
            {
              type: "button",
              text: {
                type: "plain_text",
                text: "👍",
                emoji: true,
              },
              action_id: "thumbs_up",
            },
            {
              type: "button",
              text: {
                type: "plain_text",
                text: "👎",
                emoji: true,
              },
              action_id: "thumbs_down",
            },
          ],
        },
      ],
    }
    if(ts){slackMsg.thread_ts = ts;}
    await slackClient.chat.postMessage(slackMsg);
  } catch (e) {
    throw new Error(`Error posting message to Slack: ${e.message}`);
  }
}

const disclaimer = async (channel, msg) => {
  try {
    let slackMsg = {
      channel,
      text: "Slack Disclaimer",
      blocks: [
        {
			    "type": "divider"
        },
        {
          "type": "header",
          "text": {
            "type": "plain_text",
            "text": "Disclaimer",
            "emoji": true
          }
        },
        {
          "type": "section",
          "text": {
            "type": "mrkdwn",
            "text": msg
          }
        },
        {
          "type": "divider"
        }
      ]
    }
    const result =await slackClient.chat.postMessage(slackMsg)
    return result;
  } catch (e) {
    throw new Error(`Error posting message to Slack: ${e.message}`);
  }
}

module.exports = {
  feedbackButtons,
  disclaimer
}