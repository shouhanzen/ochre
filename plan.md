# Ochre chat resilience plan (server-side ConversationModel)

## Goal

Make chat **resilient to the PWA tabbing away / backgrounding / closing** by ensuring the backend continues agent runs and can **re-sync** a reconnecting client without relying on frontend memory. This is for a **single-user** setup; we accept that in-flight memory is process-local.

Key UX requirement:
- The assistant output should appear as a **normal message bubble**, streaming into it.
- Tool events should appear as **real transcript messages** (not deferred).
- Assistant message persistence should happen **only on segment boundaries** (no per-token DB writes; no periodic flush).

## Non-goals / assumptions

- **No client auto-retry** of message submission is required.
- We do **not** target multi-worker horizontal scaling or crash-proof durability for in-flight tokens.
- If the backend process restarts mid-run, in-memory buffers are lost; DB remains the source of durable history.

## Core concept: ConversationModel (single source of truth)

Introduce a backend `ConversationModel` per `sessionId` that:
- Receives domain intents (submit message, token delta, tool events, completion).
- Owns the in-memory state for any active run and its streaming buffers.
- Writes durable records to the DB at well-defined points.
- Fans out events to connected subscribers (WebSockets).
- Can produce a **snapshot** of the current render state for reconnect/resync.

All WS/HTTP handlers should become thin adapters calling the model.

## Run job model (conceptual)

Each user request spawns a logical **run** correlated by `(sessionId, requestId)`:
- `requestId`: client-generated correlation id.
- `status`: `running | done | error | cancelled`
- `startedAt / endedAt`
- `model` (optional)

We keep in-flight run state in-memory. The DB persists the transcript messages (user/tool/assistant segments).

## Assistant “segments” (the key ordering rule)

Because tools can appear before any assistant token, and tool calls can interleave with assistant output, the assistant output must be represented as **contiguous assistant segments** separated by tool/system messages.

### Segment rules

- **Create assistant segment** (DB row) only when the **first assistant token** arrives *and there is no open segment*.
- **Append tokens** into the in-memory buffer for the open segment.
- **Close the segment** on any non-assistant transcript insertion (tool/system), and at run completion:
  - write final segment content to the DB (single update at boundary)
  - clear open segment state
- If assistant output resumes after tool messages, the next token opens a **new assistant segment** (new DB row).

This mirrors the frontend behavior: “append to the last assistant bubble if it’s still the current bubble; otherwise create a new one.”

## DB write policy (agreed compromise)

### Immediately persisted
- **User message**: inserted immediately on submit.
- **Tool messages**: inserted immediately as they occur (start/end/output).
- **System messages** (if any): inserted immediately.
- **Assistant message rows**: the *row identity* is inserted only when a segment begins (first token), but the *content* is not flushed until the segment closes.

### Persisted only on segment boundaries
- **Assistant segment content**: updated in DB only when the segment closes (tool/system boundary, done/error/cancel).

No periodic flushing; no per-token persistence.

## In-memory state shape (per session)

Maintain a per-session object like:

- `activeRun` (nullable):
  - `requestId`
  - `status`
  - `startedAt`, `endedAt`
  - `openAssistant` (nullable):
    - `messageId` (DB id of the assistant segment row)
    - `bufferText` (current assistant text not yet flushed)
  - `lastActivityAt`
  - `seq` counter (monotonic, optional)
  - `eventsRing` (optional): bounded replay buffer of `{seq, ts, type, requestId, payload}`
- `subscribers`: set of active WS connections subscribed to this session
- `lock`: to serialize transitions (avoid interleaving problems)

Memory bounds:
- cap `eventsRing` by bytes/count
- cap or stream-safe-handle `bufferText` (practically bounded by your typical responses)

## Transport contract (WS)

### Client → server

- `hello`:
  - `{ type: "hello", payload: { lastSeq?: number | null } }` (optional)
- `chat.send`:
  - `{ type: "chat.send", requestId, payload: { content } }`

### Server → client

Always include `requestId` where applicable.

- `snapshot`:
  - `{ type: "snapshot", requestId: null, payload: ConversationView }`
- `chat.started`:
  - Emitted once per run when accepted (can happen immediately on submit).
- `assistant.segment.started`:
  - `{ messageId }` (emitted when the first token arrives and we create the assistant segment row)
- `chat.delta`:
  - `{ text, messageId }` (optionally include `messageId` to make client updates simpler)
- `tool.start` / `tool.end` (and optionally `tool.output`)
- `chat.done` / `chat.error` / `chat.cancelled`

Optional: if using replay, every server->client event also includes `seq`.

## Snapshot (distilled view for reconnect/resync)

Define a “render-ready” response that the frontend can use to fully reconstruct UI:

`ConversationView`:
- `sessionId`
- `messages`: list of committed transcript messages (user/tool/system/assistant segments) from DB
- `activeRun`: nullable `{ requestId, status, startedAt, lastActivityAt }`
- `overlays`: optional mapping for the open assistant segment:
  - `{ assistantMessageId: currentBufferedContent }`
- `lastSeq` (optional)

Resync strategy:
- On WS connect, client sends `hello`.
- Server replies with `snapshot`.
- If replay is implemented and `lastSeq` is known/valid, server replays missed events from `eventsRing`.

If replay isn’t implemented, snapshot alone must include the **current buffered assistant content** overlay so the UI can display the correct partial text immediately.

## Workflow sequences

### 1) Normal foreground chat

1. Client sends `chat.send` with `requestId`.
2. ConversationModel:
   - inserts user message in DB
   - marks run `running`
   - emits `chat.started`
3. Agent begins; tool events emitted:
   - on tool boundary: close open assistant segment if any (flush once), then insert tool message rows immediately.
4. First assistant token arrives:
   - create assistant segment row (DB insert, empty content)
   - emit `assistant.segment.started {messageId}`
   - stream `chat.delta` as tokens arrive (buffer in memory)
5. On tool boundary: flush segment to DB, then insert tool messages.
6. On completion: flush any open segment to DB, emit `chat.done`.

### 2) PWA backgrounded/closed mid-run

1. WS disconnects; ConversationModel keeps running (subscribers drop, run continues).
2. In-memory buffers keep accumulating; tool messages continue to be committed immediately; assistant content remains buffered until boundary.
3. PWA reopens and reconnects:
   - client sends `hello`
   - server sends `snapshot`:
     - includes DB messages + overlay for open assistant segment (buffered content)
   - client renders immediately; streaming continues if run still active.

## Idempotency & concurrency notes

Even without client retry, treat `(sessionId, requestId)` as idempotent to prevent accidental duplicates:
- If a run is already active/done for that `requestId`, don’t insert another user message or start another run.

Use a per-session lock:
- serialize transitions (open/close segment, insert tool messages, finalize run)
- avoid race conditions between streaming callbacks and tool events.

## Frontend considerations (for “resume the same conversation”)

To feel resilient when the PWA is closed/reopened, the frontend should **reuse the same `sessionId`** by persisting it (e.g. `localStorage`), rather than creating a new session on each load.

## Implementation checklist (no code yet)

- Define `ConversationModel` API and lifecycle.
- Add a `ConversationHub`/registry keyed by `sessionId` (manage model instances).
- Refactor WS handler to:
  - on connect: subscribe + handle `hello` → `snapshot`
  - on `chat.send`: call `ConversationModel.submit_user_message(...)`
- Refactor streaming runner callbacks to report:
  - tool start/end/output (persist immediately)
  - assistant deltas (buffer; open segment on first token)
  - completion/error/cancel (flush open segment; mark run status)
- Define snapshot format and implement `snapshot()` by:
  - reading messages from DB
  - overlaying open assistant segment buffered content
- Optional (recommended): add `seq` + bounded `eventsRing` for replay.

