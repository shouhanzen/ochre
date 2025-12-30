## Ochre Backend

### Setup

Requires `uv` and Python 3.11+.

```bash
cd backend
uv sync
```

### Run

```bash
cd backend
uv run uvicorn app.main:app --reload --port 8000
```

### Environment

- `OCHRE_CORS_ORIGINS`: comma-separated origins (default `http://localhost:5173`)
- `OPENROUTER_API_KEY`: required for chat

### Gmail (/fs/email) read-only

Ochre can expose Gmail as a virtual filesystem under `/fs/email` (labels → messages).

1) Create a Google OAuth Client ID (Desktop app) and download the client JSON.
2) Generate a token JSON:

```bash
cd backend
uv run python scripts/gmail_auth.py --credentials /path/to/client.json --token /path/to/token.json
```

3) Set env vars and restart the backend:

- `OCHRE_GMAIL_CREDENTIALS_PATH`: OAuth client JSON path
- `OCHRE_GMAIL_TOKEN_PATH`: authorized user token JSON path
- `OCHRE_GMAIL_ACCOUNT_NAME` (optional, default `gmail`)
- `OCHRE_GMAIL_USER_ID` (optional, default `me`)

Or configure multiple accounts:

- `OCHRE_GMAIL_ACCOUNTS`: JSON list like
  `[{ "name": "gmail", "userId": "me", "credentialsPath": "...", "tokenPath": "..." }]`



