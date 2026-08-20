"""Credentials that fetch a fresh OAuth access token from the gcloud CLI on demand.
Lets the google-cloud-bigquery client authenticate as the logged-in gcloud user.
"""
import subprocess
import google.auth.credentials


class GcloudTokenCredentials(google.auth.credentials.Credentials):
    def __init__(self):
        super().__init__()
        self._token = None
        self._project_id = None
        self._quota_project_id = None

    def _fetch(self):
        self._token = subprocess.check_output(
            "gcloud auth print-access-token", shell=True
        ).decode().strip()

    @property
    def token(self):
        if not self._token:
            self._fetch()
        return self._token

    @token.setter
    def token(self, value):
        self._token = value

    @property
    def valid(self):
        return True

    @property
    def expired(self):
        return False

    @property
    def project_id(self):
        return self._project_id

    @project_id.setter
    def project_id(self, value):
        self._project_id = value

    @property
    def quota_project_id(self):
        return self._quota_project_id

    @quota_project_id.setter
    def quota_project_id(self, value):
        self._quota_project_id = value

    def refresh(self, request):
        self._fetch()

    def apply(self, headers, token=None):
        headers["authorization"] = "Bearer " + (token or self.token)

    def before_request(self, request, method, url, headers):
        self.apply(headers)


def get_client(project):
    from google.cloud import bigquery
    return bigquery.Client(project=project, credentials=GcloudTokenCredentials())
