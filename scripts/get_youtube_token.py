"""One-off helper: run Google's OAuth consent flow for YouTube and save the
resulting access token (plus a refresh token) straight into the running
OpenShorts dashboard's Connections tab -- nothing sensitive is printed to the
terminal.

Needs an OAuth client JSON downloaded from Google Cloud Console (APIs &
Services -> Credentials -> Create Credentials -> OAuth client ID -> Desktop
app) and the `youtube-auth` extra installed:

    pip install -e ".[youtube-auth]"
    python scripts/get_youtube_token.py --client-secret path/to/client_secret.json

A browser window opens for you to sign into Google and approve access;
this script doesn't touch that page itself, it just waits for the redirect.

Requests offline access + forces the consent screen (`access_type=offline`,
`prompt=consent`) so Google actually hands back a refresh_token -- without
that, the dashboard can only use the access token until it expires in ~1
hour. With it, the dashboard refreshes automatically and you shouldn't need
to run this again unless you revoke access or it's your first time connecting.
"""

from __future__ import annotations

import argparse
import sys

import httpx
from google_auth_oauthlib.flow import InstalledAppFlow

# YouTube Data API v3 scopes needed for the dashboard's upload + stats calls.
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--client-secret", default="client_secret.json",
        help="Path to the OAuth client JSON downloaded from Google Cloud Console.",
    )
    parser.add_argument(
        "--dashboard", default="http://127.0.0.1:8788",
        help="Base URL of the running OpenShorts dashboard.",
    )
    args = parser.parse_args()

    flow = InstalledAppFlow.from_client_secrets_file(args.client_secret, SCOPES)
    credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent")

    meta = {}
    if credentials.refresh_token:
        meta = {
            "refresh_token": credentials.refresh_token,
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "token_uri": credentials.token_uri,
        }

    try:
        resp = httpx.post(
            f"{args.dashboard}/api/connections/youtube",
            json={"access_token": credentials.token, "meta": meta},
            timeout=10.0,
        )
        resp.raise_for_status()
        result = resp.json()
    except Exception as exc:
        print(f"Got a token, but couldn't reach the dashboard at {args.dashboard}: {exc}")
        print("Is `openshorts dashboard` running? Point elsewhere with --dashboard if needed.")
        sys.exit(1)

    if not result.get("connected"):
        print("Dashboard saved the token but didn't mark YouTube as connected -- something looks off.")
        return

    if meta:
        print("YouTube connected with auto-refresh enabled -- the dashboard will keep itself "
              "signed in without you rerunning this script.")
    else:
        print(f"YouTube connected, but Google didn't return a refresh_token this time (it only hands "
              f"one out on first consent, or won't re-send it unless re-prompted). This token expires "
              f"around {credentials.expiry} (UTC) and won't auto-refresh. If posting starts failing "
              f"with an auth error, go to https://myaccount.google.com/permissions, remove access for "
              f"this app, then rerun this script.")


if __name__ == "__main__":
    main()
