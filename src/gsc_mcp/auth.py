"""OAuth (installed-app flow) for Search Console, read-only.

Environment variables:
  GSC_OAUTH_CLIENT_SECRETS  path to the OAuth client JSON (Desktop app) downloaded from Google Cloud.
                            Default: ./client_secret.json
  GSC_TOKEN_PATH            where the refresh token is stored.
                            Default: ~/.config/gsc-mcp-server/token.json

Run `gsc-mcp-server auth` once to open the browser consent screen. The token file is created with
user-only permissions where the OS supports it and is never printed.
"""
from __future__ import annotations

import os
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]


class AuthError(RuntimeError):
    """Raised with an actionable message when credentials are missing or invalid."""


def token_path() -> Path:
    return Path(os.environ.get("GSC_TOKEN_PATH") or Path.home() / ".config" / "gsc-mcp-server" / "token.json")


def client_secrets_path() -> Path:
    return Path(os.environ.get("GSC_OAUTH_CLIENT_SECRETS") or "client_secret.json")


def run_consent_flow() -> Path:
    """Interactive: opens the browser, stores the token. Used by `gsc-mcp-server auth`."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    secrets = client_secrets_path()
    if not secrets.exists():
        raise AuthError(
            f"OAuth client file not found: {secrets}. Create an OAuth client of type 'Desktop app' in Google Cloud "
            "(Search Console API enabled), download the JSON and set GSC_OAUTH_CLIENT_SECRETS to its path."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(secrets), SCOPES)
    creds = flow.run_local_server(port=0)
    path = token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(creds.to_json(), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def load_credentials():
    """Load (and refresh if needed) the stored token. Raises AuthError if there is none."""
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    path = token_path()
    if not path.exists():
        raise AuthError(f"No token at {path}. Run `gsc-mcp-server auth` once to authorize read-only access.")
    creds = Credentials.from_authorized_user_file(str(path), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError as e:
                raise AuthError(f"Token refresh failed ({type(e).__name__}). Run `gsc-mcp-server auth` again.") from e
            path.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise AuthError("Stored token is invalid. Run `gsc-mcp-server auth` again.")
    return creds
