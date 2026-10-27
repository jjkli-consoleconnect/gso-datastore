"""Deploy an explicit in-memory source ZIP through the Cloud Functions REST API."""

import io
import os
from pathlib import Path
import shutil
import subprocess
import time
import zipfile

import requests

from calendar_auth import EXPECTED_USER_EMAIL
from main import CALENDAR_ID, OAUTH_SECRET, PROJECT_ID

REGION = "europe-west2"
FUNCTION_NAME = "remedy-maintenance-calendar-sync"
API_ROOT = "https://cloudfunctions.googleapis.com/v2"
FUNCTION_RESOURCE = f"projects/{PROJECT_ID}/locations/{REGION}/functions/{FUNCTION_NAME}"
FUNCTION_DIRECTORY = Path(__file__).resolve().parent


def source_archive() -> bytes:
    sources = {
        "main.py": FUNCTION_DIRECTORY / "main.py",
        "calendar_auth.py": FUNCTION_DIRECTORY / "calendar_auth.py",
        "requirements.txt": FUNCTION_DIRECTORY / "requirements.txt",
    }
    shared = FUNCTION_DIRECTORY.parents[2] / "shared"
    for name in ("__init__.py", "logging_config.py", "pipeline_runs_logger.py"):
        sources[f"shared/{name}"] = shared / name

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for destination, source in sources.items():
            content = source.read_bytes()
            if not content:
                raise RuntimeError(f"Deployment source is empty: {source.name}")
            archive.writestr(destination, content)
    with zipfile.ZipFile(buffer) as archive:
        if set(archive.namelist()) != set(sources) or archive.testzip() is not None:
            raise RuntimeError("Deployment ZIP validation failed.")
    return buffer.getvalue()


def operator_session() -> requests.Session:
    executable = shutil.which("gcloud.cmd" if os.name == "nt" else "gcloud")
    if not executable:
        raise RuntimeError("gcloud is required only to obtain the explicitly selected operator's token.")
    environment = os.environ.copy()
    environment["CLOUDSDK_METRICS_ENVIRONMENT"] = (
        environment.get("CLOUDSDK_METRICS_ENVIRONMENT", "") + " datacloud.vscode"
    ).strip()
    result = subprocess.run(
        [executable, "auth", "print-access-token", f"--account={EXPECTED_USER_EMAIL}", "--quiet"],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    if result.returncode or not result.stdout.strip():
        raise RuntimeError(f"Cannot obtain operator credentials for {EXPECTED_USER_EMAIL}.")
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {result.stdout.strip()}"
    identity = api_json(session, "GET", "https://www.googleapis.com/oauth2/v2/userinfo")
    if identity.get("email") != EXPECTED_USER_EMAIL or identity.get("verified_email") is not True:
        session.close()
        raise RuntimeError("Deployment operator identity does not match the approved user.")
    return session


def api_json(session: requests.Session, method: str, url: str, **kwargs) -> dict:
    response = session.request(method, url, timeout=90, **kwargs)
    if not response.ok:
        raise RuntimeError(f"Cloud API {method} failed with HTTP {response.status_code}.")
    return response.json()


def deploy() -> None:
    archive = source_archive()
    print(f"Validated six-file source ZIP ({len(archive)} bytes).", flush=True)
    with operator_session() as session:
        current = api_json(session, "GET", f"{API_ROOT}/{FUNCTION_RESOURCE}")
        settings = dict(current["serviceConfig"].get("environmentVariables", {}))
        settings.update(
            TARGET_PROJECT=PROJECT_ID,
            CALENDAR_ID=CALENDAR_ID,
            CALENDAR_OAUTH_SECRET=OAUTH_SECRET,
            SYNC_WINDOW_HOURS="24",
        )
        upload = api_json(
            session,
            "POST",
            f"{API_ROOT}/projects/{PROJECT_ID}/locations/{REGION}/functions:generateUploadUrl",
            json={},
        )
        # The signed upload URL authenticates this PUT. Never attach the operator
        # token, print the URL, or persist it to disk.
        response = requests.put(
            upload["uploadUrl"],
            data=archive,
            headers={"Content-Type": "application/zip"},
            timeout=120,
        )
        if not response.ok:
            raise RuntimeError(f"Source upload failed with HTTP {response.status_code}.")
        operation = api_json(
            session,
            "PATCH",
            f"{API_ROOT}/{FUNCTION_RESOURCE}",
            params={
                "updateMask": (
                    "buildConfig.source,buildConfig.runtime,buildConfig.entryPoint,"
                    "serviceConfig.environmentVariables"
                )
            },
            json={
                "name": FUNCTION_RESOURCE,
                "buildConfig": {
                    "runtime": "python311",
                    "entryPoint": "sync_maintenance_to_calendar",
                    "source": {"storageSource": upload["storageSource"]},
                },
                "serviceConfig": {"environmentVariables": settings},
            },
        )
        operation_name = operation["name"]
        print(f"Deployment operation: {operation_name}", flush=True)
        deadline = time.monotonic() + 900
        while not operation.get("done"):
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Deployment still running; inspect operation {operation_name} before retrying.")
            time.sleep(10)
            operation = api_json(session, "GET", f"{API_ROOT}/{operation_name}")
        if "error" in operation:
            raise RuntimeError(
                f"Deployment failed (code {operation['error'].get('code')}); inspect operation {operation_name}."
            )
        deployed = api_json(session, "GET", f"{API_ROOT}/{FUNCTION_RESOURCE}")
        if deployed.get("state") != "ACTIVE":
            raise RuntimeError(f"Deployment is not ACTIVE: {deployed.get('state')}")
        print(f"ACTIVE revision: {deployed['serviceConfig']['revision']}", flush=True)
        print("Scheduler, IAM and runtime service identity were not changed.", flush=True)


if __name__ == "__main__":
    deploy()
