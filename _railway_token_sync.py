"""
PM Agent — Railway Token Sync
Writes the MS Graph refresh token back to Railway as an env var
after every successful token refresh, so it survives deploys.
"""

import os
import requests
from config import log

RAILWAY_TOKEN = os.environ.get("RAILWAY_TOKEN", "")
RAILWAY_PROJECT_ID = os.environ.get("RAILWAY_PROJECT_ID", "")
RAILWAY_ENVIRONMENT_ID = os.environ.get("RAILWAY_ENVIRONMENT_ID", "")
RAILWAY_SERVICE_ID = os.environ.get("RAILWAY_SERVICE_ID", "")

RAILWAY_API = "https://backboard.railway.com/graphql/v2"


def sync_refresh_token(new_token):
    """Write the refresh token to Railway env vars so it survives deploys."""
    if not all([RAILWAY_TOKEN, RAILWAY_PROJECT_ID, RAILWAY_ENVIRONMENT_ID, RAILWAY_SERVICE_ID]):
        log.debug(
            "Railway token sync: skipping — missing env vars "
            f"(TOKEN={'set' if RAILWAY_TOKEN else 'MISSING'}, "
            f"PROJECT={'set' if RAILWAY_PROJECT_ID else 'MISSING'}, "
            f"ENV={'set' if RAILWAY_ENVIRONMENT_ID else 'MISSING'}, "
            f"SERVICE={'set' if RAILWAY_SERVICE_ID else 'MISSING'})"
        )
        return False

    if not new_token:
        return False

    mutation = """
    mutation($input: VariableCollectionUpsertInput!) {
      variableCollectionUpsert(input: $input)
    }
    """
    variables = {
        "input": {
            "projectId": RAILWAY_PROJECT_ID,
            "environmentId": RAILWAY_ENVIRONMENT_ID,
            "serviceId": RAILWAY_SERVICE_ID,
            "variables": {
                "MS_REFRESH_TOKEN": new_token,
            },
        }
    }

    try:
        resp = requests.post(
            RAILWAY_API,
            json={"query": mutation, "variables": variables},
            headers={
                "Authorization": f"Bearer {RAILWAY_TOKEN}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        data = resp.json()
        if data.get("data", {}).get("variableCollectionUpsert"):
            log.info("Railway token sync: MS_REFRESH_TOKEN updated on Railway")
            return True
        else:
            log.warning(f"Railway token sync: API error — {data.get('errors', data)}")
            return False
    except Exception as e:
        log.warning(f"Railway token sync: Failed — {e}")
        return False
