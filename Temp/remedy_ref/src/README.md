<img src="https://avatars2.githubusercontent.com/u/2810941?v=3&s=96" alt="Google Cloud Platform logo" title="Google Cloud Platform" align="right" height="96" width="96"/>

# Ticket Agent Function

A Google Cloud Function for retrieving ticket details from Console Connect API.

## Configuration

The function uses the following environment variables for configuration:

### Authentication Configuration
- `AUTH_URL` - Authentication URL (default: 'https://auth.stage.consoleconnect.com/oauth/token')
- `PROD_HELIX_AUTH0_CLIENT_ID` - Auth0 Client ID
- `PROD_HELIX_AUTH0_CLIENT_SECRET` - Auth0 Client Secret
- `PROD_AUDIENCE` - API Audience (default: 'api.stage.corp.consoleconnect.com')

### API Configuration
- `PROD_HOST_NAME` - API Host Name (default: '10.15.0.3')
- `PROD_HOST_HEADER` - API Host Header (default: 'api.stage.corp.consoleconnect.com')

## Directory Contents
* `config.js` - configuration settings and environment variables
* `index.js` - main function implementation
* `auth.js` - authentication service implementation
* `package.json` - project dependencies

## Getting Started

1. Set up environment variables in your deployment environment or create a `.env` file
2. Install dependencies:
   ```bash
   npm install
   ```
3. Run locally:
   ```bash
   npm start
   ```

## API Usage

Send a POST request to the function with the following body:
```json
{
  "ticketId": "your-ticket-id"
}
```



Make sure to set the required environment variables in your deployment environment.

## Error Handling

The function includes comprehensive error handling for:
- Invalid request methods
- Missing ticket IDs
- Authentication failures
- API request failures
- Network errors

All errors are properly logged and return appropriate HTTP status codes with descriptive messages.
