# Souled Salesforce MCP

A minimal Model Context Protocol (MCP) server that exposes Salesforce query and update capabilities to Claude Code remote agents (and any other MCP client).

Deployed on Railway. Added as a custom connector on claude.ai. Used by the Souled AI Assessment scheduled task (see `../souled-ai-assessment/`).

## Tools exposed

| Tool | Description |
|---|---|
| `salesforce_query` | Run a SOQL SELECT and return records |
| `salesforce_update_contact` | Patch fields on a Contact record by Id |

## Architecture

```
Claude scheduled agent (remote)
    |
    | MCP over HTTP, Bearer auth
    v
Railway: souled-sf-mcp (this project)
    |
    | simple-salesforce + OAuth refresh_token
    v
Salesforce (Olami org)
```

Bearer token gates every request from claude.ai. Salesforce auth uses an External Client App + OAuth refresh_token flow (long-lived, revocable).

## Environment variables

### Required
| Var | Purpose |
|---|---|
| `SF_CLIENT_ID` | Consumer Key from the External Client App |
| `SF_CLIENT_SECRET` | Consumer Secret from the External Client App |
| `SF_REFRESH_TOKEN` | Long-lived refresh token (obtained via `scripts/get_refresh_token.py`) |
| `SF_INSTANCE_URL` | e.g. `https://jewishunityinternational.my.salesforce.com` |
| `MCP_BEARER_TOKEN` | Shared secret — claude.ai sends this as `Authorization: Bearer <token>` |

### Alternative auth modes (dev-only)
`SF_SESSION_ID` + `SF_INSTANCE_URL` — use a short-lived session from `sf org display`.
`SF_USERNAME` + `SF_PASSWORD` + `SF_SECURITY_TOKEN` + `SF_CLIENT_ID` + `SF_CLIENT_SECRET` — Username-Password OAuth (less secure, but no refresh token dance).

## Local dev

```bash
pip install -r requirements.txt
cp .env.example .env
# Fill in either session_id or refresh token mode
python server.py
```

Then from another shell:
```bash
python -c "
import asyncio
from fastmcp import Client
async def m():
    async with Client('http://localhost:8001/mcp', auth='your_bearer_token') as c:
        print(await c.list_tools())
asyncio.run(m())
"
```

## Getting a refresh token (one-time)

1. Create an External Client App in Salesforce Setup → App Manager → New External Client App
2. Enable OAuth with callback URL `http://localhost:8888/callback`
3. Scopes: `api`, `refresh_token`, `offline_access`
4. Policies: `All users may self-authorize`, `Relax IP restrictions`
5. Copy Consumer Key + Consumer Secret
6. Run locally:
   ```bash
   export SF_CLIENT_ID=...
   export SF_CLIENT_SECRET=...
   export SF_INSTANCE_URL=https://jewishunityinternational.my.salesforce.com
   python scripts/get_refresh_token.py
   ```
7. Click "Allow" in the browser. Script prints the refresh token.
8. Paste all four values into Railway env vars.

## Deploying to Railway

Standard GitHub → Railway flow:
```bash
git init && git add . && git commit -m "initial"
gh repo create Olami-Souled/souled-sf-mcp --public --source=. --push
# Then connect in Railway and set env vars
```

## Registering as a custom MCP connector on claude.ai

1. Go to https://claude.ai/customize/connectors
2. `+ Add custom connector`
3. URL: `https://<your-railway-domain>/mcp`
4. Set Authorization header: `Bearer <MCP_BEARER_TOKEN>`
5. Save

The connector will be attachable to scheduled triggers and chat sessions.

## Related projects

- `../souled-ai-assessment/` — the scheduled task instructions that use this MCP
- `../souled-coach-outcomes/` — the dashboard that surfaced the data quality problem
