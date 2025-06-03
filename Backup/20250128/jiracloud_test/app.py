import requests
from requests.auth import HTTPBasicAuth
import os
from dotenv import load_dotenv

load_dotenv()

jira_url = os.environ.get("JIRA_URL")
jira_username = os.environ.get("JIRA_USERNAME")
jira_api_token = os.environ.get("JIRA_API_TOKEN")
api_endpoint = f"{jira_url}/rest/api/3/project"

print("JIRA URL:", jira_url)
print("API Endpoint:", api_endpoint)

try:
    print("Attempting API call...")
    response = requests.get(
        api_endpoint,
        auth=HTTPBasicAuth(jira_username, jira_api_token)
    )
    response.raise_for_status()
    projects = response.json()
    print("Successfully fetched projects!")
    print("Number of projects:", len(projects))
except requests.exceptions.RequestException as e:
    print(f"Error fetching projects: {e}")