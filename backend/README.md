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



