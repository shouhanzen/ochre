## Ochre

Local single-user web app:
- OpenRouter-backed chat agent (server-side tool calling)
- Allowlisted filesystem mounts + virtual resources exposed via a **unified filesystem** (`/fs/...`)
- Daily todo system exposed as filesystem documents (`/fs/todos/...`)
- Multi-session chat (backend-managed, SQLite)
- Notion Kanban cache + pending overlays (writes require human approval)

### Prereqs

- Python 3.11+
- [`uv`](https://github.com/astral-sh/uv)
- Node.js 18+

### 1) Backend (FastAPI)

Set your OpenRouter key:

- PowerShell:

```powershell
$env:OPENROUTER_API_KEY="..."
```

- bash:

```bash
export OPENROUTER_API_KEY="..."
```

Install + run:

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

Backend health: `GET /api/health`

### 2) Frontend (Vite + React)

```bash
cd frontend
npm install
npm run dev
```

Vite proxies `/api/*` to `http://localhost:8000`.

### Mount configuration

Edit `backend/config/mounts.json`:

```json
{
  "mounts": [
    { "name": "workspace", "path": "../..", "readOnly": false }
  ]
}
```

 The agent/UI refer to files using `/fs/mnt/<mountName>/...`.

### Unified filesystem (`/fs/...`)

The agent/UI refer to everything using `/fs/...` paths, for example:
- Real mounts: `/fs/mnt/<mountName>/...`
- Todos: `/fs/todos/today.md`, `/fs/todos/YYYY-MM-DD.md`, `/fs/todos/template.md`
- Notion: `/fs/kanban/notion/boards/default/cards/<cardId>.md`

Edits to `today.md` toggle tasks by changing markdown checkboxes (`- [ ]` / `- [x]`).

### Chat sessions

- Create session: `POST /api/sessions`
- List sessions: `GET /api/sessions`
- Session chat (SSE): `POST /api/sessions/{sessionId}/chat`
- Session events (SSE): `GET /api/sessions/{sessionId}/events`

### Notion Kanban (optional)

Set env vars:
- `NOTION_API_KEY`
- `NOTION_DATABASE_ID`
- `NOTION_STATUS_PROPERTY` (default `Status`)
- `NOTION_TAGS_PROPERTY` (default `Tags`)

Pending overlays (UI-only approve/reject):
- `GET /api/kanban/pending`
- `POST /api/kanban/pending/{cardId}/approve` (include `{ "sessionId": "..." }` to inject a system message)
- `POST /api/kanban/pending/{cardId}/reject` (include `{ "sessionId": "..." }` to inject a system message)



# ochre
