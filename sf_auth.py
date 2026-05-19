"""
Salesforce authentication helper.

Supports three modes (tried in order):
  1. Session ID (for local dev) — pass SF_SESSION_ID + SF_INSTANCE_URL
  2. JWT Bearer (preferred for prod) — pass SF_CONSUMER_KEY, SF_PRIVATE_KEY,
     SF_USERNAME. Immune to password changes.
  3. OAuth refresh token — pass SF_CLIENT_ID, SF_CLIENT_SECRET,
     SF_REFRESH_TOKEN, SF_INSTANCE_URL
  4. Username-Password — pass SF_USERNAME + SF_PASSWORD (+ SF_SECURITY_TOKEN)

Uses simple-salesforce under the hood. Caches an authenticated client and
refreshes on a TTL.
"""
import base64
import json
import os
import time
import logging
import threading
import requests
from simple_salesforce import Salesforce

logger = logging.getLogger(__name__)

# Lifetime of a Salesforce access token (default is 2 hours, we refresh early)
ACCESS_TOKEN_TTL_SECONDS = 90 * 60  # refresh after 90 min


class SFAuth:
    """Thread-safe Salesforce client with auto-refresh."""

    def __init__(self):
        self._client: Salesforce | None = None
        self._last_refresh = 0
        self._lock = threading.Lock()

    def client(self) -> Salesforce:
        with self._lock:
            now = time.time()
            if (
                self._client is None
                or (now - self._last_refresh) > ACCESS_TOKEN_TTL_SECONDS
            ):
                self._client = self._build_client()
                self._last_refresh = now
            return self._client

    def _build_client(self) -> Salesforce:
        # Mode 1: Session ID (local dev)
        if os.environ.get("SF_SESSION_ID"):
            logger.info("Building SF client from session_id")
            return Salesforce(
                session_id=os.environ["SF_SESSION_ID"],
                instance_url=os.environ["SF_INSTANCE_URL"],
            )

        # Mode 2: JWT Bearer (preferred for prod — immune to password changes)
        if os.environ.get("SF_CONSUMER_KEY") and os.environ.get("SF_PRIVATE_KEY") and os.environ.get("SF_USERNAME"):
            logger.info("Building SF client via JWT Bearer")
            access_token, instance_url = self._jwt_bearer()
            return Salesforce(session_id=access_token, instance_url=instance_url)

        # Mode 3: Refresh token
        if os.environ.get("SF_REFRESH_TOKEN"):
            client_id = os.environ["SF_CLIENT_ID"]
            client_secret = os.environ["SF_CLIENT_SECRET"]
            refresh_token = os.environ["SF_REFRESH_TOKEN"]
            instance_url = os.environ["SF_INSTANCE_URL"]
            logger.info("Building SF client from refresh_token (OAuth)")
            access_token = self._refresh_access_token(
                client_id, client_secret, refresh_token, instance_url
            )
            return Salesforce(session_id=access_token, instance_url=instance_url)

        # Mode 3: Username-Password OAuth (simpler, acceptable for prod)
        if os.environ.get("SF_USERNAME") and os.environ.get("SF_PASSWORD"):
            logger.info("Building SF client via username-password OAuth")
            return Salesforce(
                username=os.environ["SF_USERNAME"],
                password=os.environ["SF_PASSWORD"],
                security_token=os.environ.get("SF_SECURITY_TOKEN", ""),
                consumer_key=os.environ.get("SF_CLIENT_ID"),
                consumer_secret=os.environ.get("SF_CLIENT_SECRET"),
                domain=os.environ.get("SF_DOMAIN", "login"),
            )

        raise RuntimeError(
            "No SF credentials found. Set one of:\n"
            "  1. SF_SESSION_ID + SF_INSTANCE_URL (dev)\n"
            "  2. SF_CLIENT_ID + SF_CLIENT_SECRET + SF_REFRESH_TOKEN + SF_INSTANCE_URL (refresh token)\n"
            "  3. SF_USERNAME + SF_PASSWORD + SF_SECURITY_TOKEN + SF_CLIENT_ID + SF_CLIENT_SECRET (password grant)"
        )

    @staticmethod
    def _jwt_bearer() -> tuple[str, str]:
        """Exchange a signed JWT assertion for an SF access token (JWT Bearer Flow)."""
        import hmac, hashlib
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
        consumer_key = os.environ["SF_CONSUMER_KEY"]
        username = os.environ["SF_USERNAME"]
        private_key_pem = os.environ["SF_PRIVATE_KEY"].encode()
        header = base64.urlsafe_b64encode(json.dumps({"alg": "RS256", "typ": "JWT"}).encode()).rstrip(b"=")
        payload = base64.urlsafe_b64encode(json.dumps({
            "iss": consumer_key,
            "sub": username,
            "aud": "https://login.salesforce.com",
            "exp": int(time.time()) + 180,
        }).encode()).rstrip(b"=")
        signing_input = header + b"." + payload
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        key = load_pem_private_key(private_key_pem, password=None)
        sig = key.sign(signing_input, asym_padding.PKCS1v15(), hashes.SHA256())
        assertion = (signing_input + b"." + base64.urlsafe_b64encode(sig).rstrip(b"=")).decode()
        resp = requests.post(
            "https://login.salesforce.com/services/oauth2/token",
            data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
            timeout=30,
        )
        if not resp.ok:
            raise RuntimeError(f"SF JWT auth failed ({resp.status_code}): {resp.text}")
        d = resp.json()
        return d["access_token"], d["instance_url"]

    @staticmethod
    def _refresh_access_token(client_id, client_secret, refresh_token, instance_url) -> str:
        """Exchange refresh_token for a new access_token."""
        # Token URL is based on the login host, not the instance URL
        token_url = "https://login.salesforce.com/services/oauth2/token"
        resp = requests.post(
            token_url,
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
            },
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
        if "access_token" not in body:
            raise RuntimeError(f"Token refresh failed: {body}")
        logger.info("Successfully refreshed SF access token")
        return body["access_token"]
