"""
Technomak reader agent - the public "Ask about the news" chat on the digest
page. A 5-node LangGraph graph, one run per chat turn:

    understand_query --(new topic / sources don't cover it)--> research
            |                                                     |
            +--(follow-up on a topic already researched)--+       |
                                                          v       v
                                         summarize -> verify -> respond -> END

Conversation state (history, topic, and the sources found so far) is saved
per conversation_id by LangGraph's SqliteSaver in its own file,
reader_agent.db. It never touches technomak.db - this feature only reads
the web and publishes nothing. SqliteSaver rather than the in-memory
checkpointer so a chat survives a server restart; it needs one extra
package (langgraph-checkpoint-sqlite) and no other setup.

Follow-ups skip research: the sources found for a topic are cached on the
conversation, so "tell me more" or "what about the costs?" re-summarizes
what was already fetched instead of spending another web search.

Like agent.py, this module doesn't import technomak_app. The app calls
configure(call_llm) at startup, so all LLM traffic uses the app's one
client. The Tavily call is shared with agent.py (tavily_search).

Failures never raise out of the graph: a node sets `error`, the graph jumps
to respond, and the Flask route turns that into a JSON error.
"""

import json
import os
import re
import sqlite3
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from typing import List, Optional, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from agent import tavily_search

READER_DB_PATH = os.environ.get(
    "READER_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "reader_agent.db"))

MAX_QUERY_CHARS = 300
HISTORY_FOR_LLM = 10        # messages of history the LLM sees
MAX_STORED_HISTORY = 40     # messages kept on the conversation
SOURCES_PER_SEARCH = 6      # new sources added by one research pass
MAX_CACHED_SOURCES = 24     # per conversation, oldest dropped first
MAX_SUMMARY_SOURCES = 8     # sources shown to summarize/verify

_RECENCY_RE = re.compile(
    r"\b(latest|recent|recently|today|this week|this month|newest|current|"
    r"now|breaking|update|updates)\b", re.I)
_DETAILED_RE = re.compile(
    r"\b(detailed|in detail|more detail|tell me more|explain further|"
    r"elaborate|expand on|go deeper|deep dive)\b", re.I)

_deps = {}


def configure(call_llm):
    _deps["call_llm"] = call_llm


class ReaderState(TypedDict, total=False):
    conversation_id: str
    message_history: List[dict]     # [{role, content}]
    user_query: str
    query_type: str                 # "new_topic" | "followup"
    topic: str
    detail_level: str               # "short" | "detailed"
    search_queries: List[str]
    raw_sources: List[dict]         # {title, url, snippet, published_date, topic}
    key_points: List[str]
    verified_points: List[str]
    response_text: str
    sources_used: List[dict]
    # Internal plumbing between nodes, not part of the spec'd state:
    in_scope: bool
    answer: str                     # the conversational sentence(s)
    point_sources: List[List[int]]  # per key_point, 1-based ids into context_sources
    context_sources: List[dict]     # the numbered sources summarize saw
    verification_note: str
    error: Optional[str]


# --- Helpers ---------------------------------------------------------------

def _llm(system_prompt, user_prompt, max_tokens):
    if "call_llm" not in _deps:
        return None, "Reader agent is not configured."
    return _deps["call_llm"](system_prompt, user_prompt, max_tokens=max_tokens)


def _parse_json_object(raw):
    if not raw:
        return None
    cleaned = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(cleaned[start:end + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _history_text(state):
    recent = (state.get("message_history") or [])[-HISTORY_FOR_LLM:]
    if not recent:
        return "(no earlier messages)"
    return "\n".join(f"{m['role']}: {m['content'][:500]}" for m in recent)


def _same_topic(a, b):
    return (a or "").strip().lower() == (b or "").strip().lower()


def _sources_for_topic(state):
    topic = state.get("topic")
    cached = state.get("raw_sources") or []
    matching = [s for s in cached if _same_topic(s.get("topic"), topic)]
    return matching[-MAX_SUMMARY_SOURCES:]


def _format_sources(sources):
    return "\n\n".join(
        f"[{i}] {s['title']} ({s.get('published_date') or 'date unknown'})\n{s['snippet']}"
        for i, s in enumerate(sources, 1))


# --- Node 1: understand_query ----------------------------------------------

def understand_query(state: ReaderState) -> dict:
    query = state.get("user_query", "")
    current_topic = state.get("topic") or ""
    requested_detail = state.get("detail_level") or ""

    raw, err = _llm(
        f"Today is {date.today():%d %B %Y}. You route questions for a news "
        "assistant on an industrial/EPC company's digest page (oil & gas, "
        "construction, energy, industrial tech, business news).\n\n"
        "Respond ONLY with a JSON object, no markdown fences:\n"
        "{\"in_scope\": true if this is a question about news, companies, "
        "industries, markets, technology or current events - false for "
        "anything else (coding help, creative writing, personal advice, "
        "chit-chat),\n"
        " \"query_type\": \"followup\" if it continues the current topic, "
        "\"new_topic\" if it starts a different subject,\n"
        " \"topic\": for a followup, the current topic copied EXACTLY; "
        "otherwise a short specific topic (max ~8 words),\n"
        " \"detail_level\": \"detailed\" if the user asks for more detail, "
        "an explanation or depth, else \"short\",\n"
        " \"search_queries\": 1-3 concrete web search queries for the "
        "topic (include names, places, and the current year for recent "
        "news)}",
        f"Current topic: {current_topic or '(none yet)'}\n\n"
        f"Conversation so far:\n{_history_text(state)}\n\nNew message: {query}",
        max_tokens=800,
    )
    if err:
        return {"error": f"understand_query: {err}"}
    data = _parse_json_object(raw)
    if data is None:
        return {"error": "understand_query: the model returned malformed JSON."}

    if data.get("in_scope") is False:
        return {"in_scope": False}

    query_type = "followup" if data.get("query_type") == "followup" else "new_topic"
    topic = " ".join(str(data.get("topic") or "").split())[:120]
    if query_type == "followup" and current_topic:
        # Keep the existing topic (and so its cached sources) unless the
        # model returned something that clearly isn't it.
        topic = current_topic if not topic or _same_topic(topic, current_topic) else topic
        if not _same_topic(topic, current_topic):
            query_type = "new_topic"
    elif not current_topic:
        query_type = "new_topic"
    topic = topic or query[:120]

    if requested_detail in ("short", "detailed"):
        detail = requested_detail
    elif data.get("detail_level") == "detailed" or _DETAILED_RE.search(query):
        detail = "detailed"
    else:
        detail = "short"

    queries = [" ".join(str(q).split())[:200] for q in data.get("search_queries") or []]
    queries = [q for q in queries if q][:3]
    return {"in_scope": True, "query_type": query_type, "topic": topic,
            "detail_level": detail, "search_queries": queries}


def route_after_understand(state: ReaderState) -> str:
    if state.get("error") or state.get("in_scope") is False:
        return "respond"
    if state.get("query_type") == "new_topic" or not _sources_for_topic(state):
        return "research"
    return "summarize"


# --- Node 2: research ------------------------------------------------------

def research(state: ReaderState) -> dict:
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return {"error": "research: TAVILY_API_KEY is not set."}
    topic = state["topic"]
    queries = state.get("search_queries") or [topic]

    query_text = state.get("user_query", "")
    options = {}
    recent = bool(_RECENCY_RE.search(query_text))
    if recent:
        low = query_text.lower()
        options = {"topic": "news",
                   "time_range": "day" if "today" in low else
                                 "week" if "this week" in low else "month"}

    per_query, failures = [], []
    for q in queries:
        results, err = tavily_search(api_key, q, SOURCES_PER_SEARCH, **options)
        if err:
            failures.append(err)
        else:
            per_query.append(results)
    if not per_query:
        return {"error": "research: every web search failed - " + "; ".join(failures)}

    cached = state.get("raw_sources") or []
    seen = {s["url"].rstrip("/").lower() for s in cached}
    new = []
    for rank in range(SOURCES_PER_SEARCH):          # interleave the queries
        for results in per_query:
            if rank >= len(results):
                continue
            r = results[rank]
            url = str(r.get("url") or "").strip()
            key = url.rstrip("/").lower()
            if not url.lower().startswith(("http://", "https://")) or key in seen:
                continue
            seen.add(key)
            new.append({
                "title": " ".join(str(r.get("title") or url).split())[:200],
                "url": url,
                "snippet": " ".join(str(r.get("content") or "").split())[:400],
                "published_date": str(r.get("published_date") or "")[:40],
                "topic": topic,
            })
    if recent:
        # Newest first; undated results sink to the end. Tavily dates may be
        # RFC-2822 or ISO strings, so sort on the parsed value, not the text.
        def _when(s):
            raw_date = s["published_date"]
            for parse in (parsedate_to_datetime,
                          lambda v: datetime.fromisoformat(v.replace("Z", "+00:00"))):
                try:
                    when = parse(raw_date)
                    if when.tzinfo is None:
                        when = when.replace(tzinfo=timezone.utc)
                    return when.timestamp()
                except (TypeError, ValueError, IndexError):
                    continue
            return 0
        new.sort(key=_when, reverse=True)
    new = new[:SOURCES_PER_SEARCH]
    if not new and not _sources_for_topic(state):
        return {"error": "research: the web search found nothing on that topic."}
    # Append, don't replace: earlier topics stay available to follow-ups.
    return {"raw_sources": (cached + new)[-MAX_CACHED_SOURCES:]}


# --- Node 3: summarize -----------------------------------------------------

def summarize(state: ReaderState) -> dict:
    if state.get("error"):
        return {}
    sources = _sources_for_topic(state)
    detailed = state.get("detail_level") == "detailed"
    shape = ("\"answer\": a paragraph of 4-6 sentences that directly answers "
             "the question, \"points\": 5-8 key points" if detailed else
             "\"answer\": 1-2 sentences that directly answer the question, "
             "\"points\": 3-5 key points, each under 25 words")

    raw, err = _llm(
        "You answer readers' questions on a company news digest, using ONLY "
        "the numbered web sources provided. Every point must come from a "
        "specific source; list which source number(s) support it. Never add "
        "numbers, names or dates that aren't in the sources. If the sources "
        "don't answer the question, say so plainly in the answer.\n\n"
        "Respond ONLY with a JSON object, no markdown fences:\n"
        "{" + shape + " as a list of {\"text\": the point, \"sources\": "
        "[source numbers]}}. Do not put source numbers inside the text.",
        f"Conversation so far:\n{_history_text(state)}\n\n"
        f"Question: {state.get('user_query', '')}\nTopic: {state.get('topic', '')}"
        f"\n\nSources:\n{_format_sources(sources)}",
        max_tokens=2200 if detailed else 1500,
    )
    if err:
        return {"error": f"summarize: {err}"}
    data = _parse_json_object(raw)
    if data is None or not isinstance(data.get("points"), list):
        return {"error": "summarize: the model returned malformed JSON."}

    points, point_sources = [], []
    for p in data["points"]:
        if not isinstance(p, dict):
            continue
        text = " ".join(str(p.get("text") or "").split())
        ids = []
        for i in p.get("sources") or []:
            try:
                i = int(i)
            except (TypeError, ValueError):
                continue
            if 1 <= i <= len(sources) and i not in ids:
                ids.append(i)
        if text and ids:            # untraceable points are dropped here
            points.append(text)
            point_sources.append(ids)
    return {"answer": str(data.get("answer") or "").strip(),
            "key_points": points, "point_sources": point_sources,
            "context_sources": sources}


# --- Node 4: verify --------------------------------------------------------

def verify(state: ReaderState) -> dict:
    if state.get("error"):
        return {}
    sources = state.get("context_sources") or []
    points = state.get("key_points") or []
    point_sources = state.get("point_sources") or []
    numbered = "\n".join(f"{n}. {p} (cites {point_sources[n - 1]})"
                         for n, p in enumerate(points, 1)) or "(none)"

    raw, err = _llm(
        "You fact-check a news answer against its sources. A point is "
        "supported only if the sources it cites actually state it; "
        "paraphrase is fine, added facts are not.\n\n"
        "Respond ONLY with a JSON object, no markdown fences:\n"
        "{\"supported\": [numbers of the points that ARE supported], "
        "\"answer\": ONLY the ANSWER sentence(s), with any unsupported claim "
        "removed - never include the points, labels or source numbers "
        "(return it unchanged if it is fully supported)}",
        f"=== ANSWER ===\n{state.get('answer', '')}\n\n=== POINTS ===\n{numbered}"
        f"\n\n=== SOURCES ===\n{_format_sources(sources)}",
        max_tokens=1200,
    )
    data = _parse_json_object(raw) if not err else None
    if data is None or not isinstance(data.get("supported"), list):
        kept = list(range(1, len(points) + 1))
        answer = state.get("answer", "")
        note = "I couldn't double-check these points against the sources this time."
    else:
        kept = []
        for n in data["supported"]:
            try:
                n = int(n)
            except (TypeError, ValueError):
                continue
            if 1 <= n <= len(points) and n not in kept:
                kept.append(n)
        kept.sort()
        answer = str(data.get("answer") or "").strip()
        original = state.get("answer", "")
        # A trimmed answer can only get shorter; anything longer, or carrying
        # the points/labels, is the model echoing its input - keep the original.
        if (not answer or len(answer) > len(original) * 1.2 + 20
                or re.search(r"(?i)\bpoints?:|\(cites|===|^answer:", answer)):
            answer = original
        note = ""

    verified = [points[n - 1] for n in kept]
    used_ids = []
    for n in kept:
        for i in point_sources[n - 1]:
            if i not in used_ids:
                used_ids.append(i)
    used = [{"title": sources[i - 1]["title"], "url": sources[i - 1]["url"],
             "published_date": sources[i - 1].get("published_date", "")}
            for i in sorted(used_ids)]
    if not verified and not note:
        note = "I couldn't find points the sources clearly support."
    return {"verified_points": verified, "sources_used": used,
            "answer": answer, "verification_note": note}


# --- Node 5: respond -------------------------------------------------------

def respond(state: ReaderState) -> dict:
    if state.get("error"):
        return {}       # the route reports the error; history is untouched
    if state.get("in_scope") is False:
        text = ("I can only help with questions about the news - companies, "
                "industries, markets and technology. Try asking about a "
                "recent development.")
        return {"response_text": text,
                "message_history": _append_turn(state, text)}

    parts = [state.get("answer") or "Here is what the sources say."]
    if state.get("verified_points"):
        parts.append("\n".join(f"• {p}" for p in state["verified_points"]))
    if state.get("verification_note"):
        parts.append(state["verification_note"])
    if state.get("sources_used"):
        parts.append("Sources:\n" + "\n".join(
            f"- {s['title']} ({s['url']})" for s in state["sources_used"]))
    text = "\n\n".join(parts)
    return {"response_text": text, "message_history": _append_turn(state, text)}


def _append_turn(state, reply):
    history = (state.get("message_history") or []) + [
        {"role": "user", "content": state.get("user_query", "")},
        {"role": "assistant", "content": reply},
    ]
    return history[-MAX_STORED_HISTORY:]


# --- Graph -----------------------------------------------------------------

def build_graph(checkpointer=None):
    g = StateGraph(ReaderState)
    g.add_node("understand_query", understand_query)
    g.add_node("research", research)
    g.add_node("summarize", summarize)
    g.add_node("verify", verify)
    g.add_node("respond", respond)
    g.add_edge(START, "understand_query")
    g.add_conditional_edges("understand_query", route_after_understand,
                            {"research": "research", "summarize": "summarize",
                             "respond": "respond"})
    g.add_edge("research", "summarize")
    g.add_edge("summarize", "verify")
    g.add_edge("verify", "respond")
    g.add_edge("respond", END)
    return g.compile(checkpointer=checkpointer)


_conn = sqlite3.connect(READER_DB_PATH, check_same_thread=False)
graph = build_graph(SqliteSaver(_conn))


def ask(conversation_id, query, detail_level=None):
    """Run one chat turn. Per-turn fields are reset here; history, topic and
    raw_sources carry over from the conversation's saved state."""
    config = {"configurable": {"thread_id": conversation_id}}
    return graph.invoke({
        "conversation_id": conversation_id,
        "user_query": query,
        "detail_level": detail_level if detail_level in ("short", "detailed") else "",
        "search_queries": [], "key_points": [], "verified_points": [],
        "point_sources": [], "context_sources": [], "sources_used": [],
        "answer": "", "response_text": "", "verification_note": "",
        "in_scope": True, "error": None,
    }, config)


if __name__ == "__main__":
    # Smoke test: python reader_agent.py <conversation_id> "<question>"
    import sys
    import technomak_app as app_module
    configure(app_module.call_llm)
    result = ask(sys.argv[1], sys.argv[2])
    print(result.get("error") or result["response_text"])
