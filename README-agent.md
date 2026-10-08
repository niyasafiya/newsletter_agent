# "Ask about the news" agent (`reader_agent.py`)

A public chat on the digest page. Readers ask about industry news; the agent
searches the web live, summarises what it finds, fact-checks the summary
against the sources, and answers with links. It publishes nothing and never
touches `technomak.db`.

- **Frontend:** `src/components/AskAgent.tsx` — the floating "Ask about the news"
  button (bottom-right) that opens a chat panel. Calls `askNewsAgent()` in
  `src/api.ts`.
- **Route:** `POST /api/v1/ask` in `technomak_app.py` — public, no login.
- **Graph:** `reader_agent.py` — a LangGraph graph, one run per chat turn.
- **Memory:** `reader_agent.db` — a separate SQLite file where LangGraph's
  `SqliteSaver` keeps each conversation (history, topic, sources found) under
  its `conversation_id`. Conversations survive a server restart. Delete the
  file to wipe all chats.

(Not to be confused with `agent.py`, the admin console's draft-and-review
research agent.)

## The 5 nodes

```
understand_query ──(new topic, or cached sources don't cover it)──> research
       │                                                              │
       └──(follow-up on a topic already researched)──┐                │
                                                     ▼                ▼
                                       summarize ──> verify ──> respond ──> end
```

1. **understand_query** — one LLM call. Decides whether the message is a
   follow-up or a new topic, sets the `topic`, picks `detail_level` ("short" by
   default, "detailed" for "tell me more" / "explain further"), and suggests 1–3
   search queries. Off-topic requests (coding help, poems…) are declined
   here, with no search.
2. **research** — up to 3 Tavily searches. Deduplicates by URL and adds at most
   6 new sources. Words like "latest" or "this week" switch Tavily to recent
   news and sort newest first. Results are **appended** to the conversation's
   cached sources (max 24), not replaced.
3. **summarize** — one LLM call over the sources for the current topic: a short
   answer plus 3–5 key points (or a paragraph plus 5–8 points when detailed).
   Every point must cite a source number; points that don't are dropped.
4. **verify** — one LLM call, single pass (no revision loop — this is live
   chat). Drops points the cited sources don't actually support and trims
   unsupported claims from the answer. If the check itself fails, the answer
   is shown with a "couldn't double-check" note.
5. **respond** — builds the reply (answer, points, sources list) and adds the
   turn to the conversation history.

## Why follow-ups skip research

Each cached source remembers the topic it was found for. When a message
continues the same topic, `understand_query` keeps the topic unchanged, so
the graph goes straight to `summarize` over the sources it already has. That
makes follow-ups ("tell me more", "who won the contract?") answer in a few
seconds instead of 15–60, and saves Tavily searches and Groq tokens. A new
subject — or a follow-up whose topic has no cached sources — triggers a
fresh search.

## Abuse protection

- Questions over 300 characters are rejected.
- The LLM only sees the last 10 messages of history; the saved history keeps
  at most 40.
- Rate limit: 8 questions per minute per client IP. Behind the Vite dev
  proxy every visitor shares one IP, so this limit is effectively site-wide
  in development.
- Readers see a plain error message; the detailed reason is printed in the
  backend's terminal as `[ask <conversation_id>] ...`.

## Environment variables

| Variable | Needed for |
|---|---|
| `GROQ_API_KEY` (or `OPENAI_API_KEY`) | The LLM that plans, summarises and fact-checks. Same key as the rest of the app. |
| `TAVILY_API_KEY` | Web search (tavily.com). Same key the admin agent uses. |
| `READER_DB_PATH` | Optional. Where the chat memory lives (default `reader_agent.db` next to the app). |

Packages: `pip install langgraph langgraph-checkpoint-sqlite` (on top of the
app's usual `flask openpyxl requests`).

## Running it

```
./start_backend.sh     # backend on 127.0.0.1:5050, loads keys from ~/.technomak_keys
```

The React site (port 8443) proxies `/api` to it; the chat button appears on
every page except the AI Influencer page. To test the backend alone:

```
curl -s -H 'Content-Type: application/json' \
  -d '{"query":"What are the latest ADNOC contract awards?"}' \
  http://127.0.0.1:5050/api/v1/ask
```

Omit `conversation_id` to start a new conversation; send back the returned
`conversation_id` to continue it.
