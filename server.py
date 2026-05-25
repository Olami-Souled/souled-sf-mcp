"""
Salesforce MCP server for the Olami/Souled org.

Exposes two tools to a claude.ai remote agent:
  - salesforce_query: Run a SOQL query, return records as JSON
  - salesforce_update_contact: Update specific fields on a Contact record

Auth: Bearer token in Authorization header (set via MCP_BEARER_TOKEN env var).
This is a minimal shared-secret scheme suitable for single-integration use.

Deployed on Railway; added as a custom MCP connector on claude.ai.
"""
import os
import logging
from typing import Any
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware

from sf_auth import SFAuth

# Load .env for local dev (no-op on Railway where vars are already set)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Authentication middleware — checks bearer token on every request
# ------------------------------------------------------------------
EXPECTED_BEARER = os.environ.get("MCP_BEARER_TOKEN", "")


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """
    Accept either:
      - Authorization: Bearer <token>   (for API clients like FastMCP Client)
      - ?k=<token> in the URL            (for claude.ai custom connector, which
         has no native Bearer field; the token is embedded in the URL)
    """
    async def dispatch(self, request: Request, call_next):
        # Allow the health check through without auth so Railway can poll it
        if request.url.path in ("/", "/health"):
            return await call_next(request)

        if not EXPECTED_BEARER:
            return JSONResponse(
                {"error": "MCP_BEARER_TOKEN not configured on server"},
                status_code=500,
            )

        token = None

        # Check Authorization header first
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[len("Bearer "):].strip()

        # Fallback to URL query parameter
        if not token:
            token = request.query_params.get("k", "")

        if not token or token != EXPECTED_BEARER:
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        return await call_next(request)


# ------------------------------------------------------------------
# FastMCP server with Salesforce tools
# ------------------------------------------------------------------
mcp = FastMCP(
    name="Souled Salesforce",
    instructions=(
        "Query and update the Olami/Souled Salesforce org. "
        "Use salesforce_query for SOQL SELECT statements. "
        "Use salesforce_update_contact to patch fields on a Contact by Id."
    ),
)

_sf_auth = SFAuth()


@mcp.tool()
def salesforce_query(soql: str) -> dict[str, Any]:
    """
    Run a SOQL SELECT query against the Olami Salesforce org.

    Args:
        soql: A valid SOQL SELECT statement. Example:
            SELECT Id, Name FROM Contact WHERE Id = '003...'

    Returns:
        Dict with keys:
          - totalSize: number of records
          - done: true if all records returned
          - records: list of record dicts (Salesforce metadata stripped)
    """
    if not soql or not soql.strip():
        raise ValueError("soql is required")
    if not soql.strip().lower().startswith("select"):
        raise ValueError("Only SELECT queries are allowed via this tool")

    logger.info(f"SOQL: {soql[:200]}")
    sf = _sf_auth.client()
    result = sf.query_all(soql)

    # Strip Salesforce metadata from records for cleaner output
    cleaned = [_clean_record(r) for r in result.get("records", [])]
    return {
        "totalSize": result.get("totalSize"),
        "done": result.get("done"),
        "records": cleaned,
    }


@mcp.tool()
def salesforce_update_contact(contact_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    """
    Update specific fields on a Contact record.

    Args:
        contact_id: The Salesforce Id of the Contact (15 or 18 chars).
        fields: Dict of field API name -> new value. Example:
            {
                "AI_SO_Verdict__c": "Unlikely",
                "AI_SO_Confidence__c": 95,
                "AI_SO_Assessment__c": "...long text...",
                "AI_SO_Assessed_Date__c": "2026-04-19T10:00:00.000+0000"
            }

    Returns:
        Dict with keys:
          - success: bool
          - contact_id: the Id that was updated
          - fields_updated: list of field names updated
    """
    if not contact_id:
        raise ValueError("contact_id is required")
    if not fields or not isinstance(fields, dict):
        raise ValueError("fields must be a non-empty dict")

    logger.info(f"Updating Contact {contact_id} fields: {list(fields.keys())}")
    sf = _sf_auth.client()
    status_code = sf.Contact.update(contact_id, fields)

    success = status_code in (200, 204)
    return {
        "success": success,
        "contact_id": contact_id,
        "fields_updated": list(fields.keys()),
        "status_code": status_code,
    }


def _clean_record(record: dict) -> dict:
    """Strip Salesforce metadata from a record, recursively on nested relationships."""
    out = {}
    for k, v in record.items():
        if k == "attributes":
            continue
        if isinstance(v, dict):
            out[k] = _clean_record(v)
        elif isinstance(v, list):
            out[k] = [_clean_record(x) if isinstance(x, dict) else x for x in v]
        else:
            out[k] = v
    return out


# ------------------------------------------------------------------
# Build the ASGI app
# ------------------------------------------------------------------
# FastMCP exposes a streamable HTTP transport at /mcp
app = mcp.http_app(path="/mcp")

# Wrap with bearer auth middleware
app.add_middleware(BearerAuthMiddleware)


# ------------------------------------------------------------------
# Health check routes (added directly on the Starlette app)
# ------------------------------------------------------------------
async def health(request: Request) -> JSONResponse:
    return JSONResponse({
        "status": "ok",
        "has_bearer_token": bool(EXPECTED_BEARER),
        "has_sf_creds": bool(
            os.environ.get("SF_SESSION_ID")
            or (os.environ.get("SF_CLIENT_ID") and os.environ.get("SF_CLIENT_SECRET") and os.environ.get("SF_REFRESH_TOKEN"))
            or (os.environ.get("SF_CONSUMER_KEY") and os.environ.get("SF_PRIVATE_KEY") and os.environ.get("SF_USERNAME"))
        ),
        "has_instance_url": bool(os.environ.get("SF_INSTANCE_URL") or os.environ.get("SF_CONSUMER_KEY")),
    })


async def index(request: Request) -> PlainTextResponse:
    return PlainTextResponse(
        "Souled Salesforce MCP. POST /mcp with Bearer auth to use. "
        "GET /health for status."
    )


# Register the health routes (FastMCP's app is a Starlette app)
app.router.routes.insert(0, __import__("starlette.routing", fromlist=["Route"]).Route("/", index))
app.router.routes.insert(0, __import__("starlette.routing", fromlist=["Route"]).Route("/health", health))


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8001))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
