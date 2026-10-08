"""
Technomak research agent - a 6-node LangGraph pipeline that researches a
topic for one digest section and drafts a single entry for admin review.

    decide_topic -> research -> gather_db_context -> draft -> self_check
                                                       ^           |
                                                       +-- revise -+
                                                                   |
                                                         structure_output -> END

This module deliberately does NOT import technomak_app: when the app runs as
`python technomak_app.py` that import would execute the whole app a second
time. Instead the app calls configure() once at startup and hands over its
existing helpers (call_llm, recent_entries_digest_text, SECTION_META,
_ALLOWED_TAGS), so there is exactly one LLM client and one DB read path.

Failures never raise out of the graph: a node that hits a missing key, a
failed HTTP call or malformed LLM JSON sets `error` on the state, every later
node passes straight through, and structure_output marks the run
status="error". Non-fatal problems (one search query failing, the critic
being unable to run) are collected in `warnings`.

Human feedback re-enters the same compiled graph at `draft` by seeding a
fresh thread as if gather_db_context had just finished (see
resume_with_feedback), so the topology above is the only one there is.
"""

import json
import os
import re
import uuid
from datetime import date
from typing import List, Optional, TypedDict

import requests
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

MAX_REVISIONS = 2
MAX_SOURCES = 8
RESULTS_PER_QUERY = 5
TAVILY_URL = "https://api.tavily.com/search"

# The tag list the app's AI creator prompts use (a subset of _ALLOWED_TAGS).
DRAFT_TAGS = ["Active", "Deployed", "Testing", "Development", "Risk",
              "Opportunity", "Industry", "Pending", "Leadership", "New"]

# Filled in by configure() - see module docstring.
_deps = {}


def configure(call_llm, digest_text, section_meta, allowed_tags):
    _deps.update(call_llm=call_llm, digest_text=digest_text,
                 section_meta=section_meta, allowed_tags=allowed_tags)


class Source(TypedDict):
    title: str
    url: str
    snippet: str


class AgentState(TypedDict, total=False):
    section: str
    topic: str
    search_queries: List[str]
    raw_sources: List[Source]
    db_context: str
    subject: str
    body: str
    tag: str
    critic_feedback: str
    human_feedback: str
    revision_count: int
    status: str
    # Not in the diagram's state box, but needed for safe hand-off:
    entry: dict            # final {section, title, body, tag}
    warnings: List[str]
    error: Optional[str]


# --- Helpers ---------------------------------------------------------------

def _llm(system_prompt, user_prompt, max_tokens=900):
    """The app's call_llm(): returns (text, None) or (None, error)."""
    if "call_llm" not in _deps:
        return None, "Agent is not configured (configure() was never called)."
    return _deps["call_llm"](system_prompt, user_prompt, max_tokens=max_tokens)


def _parse_json_object(raw):
    """Pull the first JSON object out of an LLM reply (tolerates ``` fences
    and stray prose around it). Returns a dict, or None if malformed."""
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


def _section_label(section):
    return _deps.get("section_meta", {}).get(section, section)


def _section_digest(section):
    text = _deps["digest_text"](limit=25, section=section)
    return text or "(Nothing has been published in this section yet.)"


def _allowed_tags():
    allowed = _deps.get("allowed_tags") or set(DRAFT_TAGS)
    return [t for t in DRAFT_TAGS if t in allowed]


def _format_sources(sources):
    if not sources:
        return "(no web sources)"
    return "\n\n".join(
        f"[S{i}] {s['title']} ({s['url']})\n{s['snippet']}"
        for i, s in enumerate(sources, 1)
    )


def _evidence_block(state):
    parts = [
        "=== WEB SOURCES ===\n" + _format_sources(state.get("raw_sources") or []),
        "=== INTERNAL CONTEXT (already published in this section) ===\n"
        + (state.get("db_context") or "(none)"),
    ]
    if state.get("human_feedback"):
        parts.append("=== ADMIN FEEDBACK (the reviewer's own words - facts "
                     "stated here count as supported) ===\n"
                     + state["human_feedback"])
    return "\n\n".join(parts)


def _halted(state):
    return bool(state.get("error"))


def _warn(state, message):
    return (state.get("warnings") or []) + [message]


def tavily_search(api_key, query, max_results, **options):
    """One Tavily search. Returns (results, None) or ([], error_text).
    Shared with reader_agent.py; `options` are extra Tavily fields such as
    topic="news" or time_range="week"."""
    try:
        resp = requests.post(
            TAVILY_URL,
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json={"query": query, "max_results": max_results,
                  "search_depth": "basic", **options},
            timeout=20,
        )
        resp.raise_for_status()
        results = resp.json().get("results") or []
    except (requests.RequestException, ValueError, AttributeError) as exc:
        return [], str(exc)
    return [r for r in results if isinstance(r, dict)], None


# --- Node 1: decide_topic --------------------------------------------------

def decide_topic(state: AgentState) -> dict:
    section = state.get("section")
    if section not in _deps.get("section_meta", {}):
        return {"error": f"Unknown section '{section}'."}
    label = _section_label(section)
    topic = (state.get("topic") or "").strip()
    # Decide Topic reads internal context before choosing, per the diagram.
    # gather_db_context still owns writing db_context onto the state.
    existing = _section_digest(section)

    if topic:
        task = (f"The admin asked for this topic: \"{topic}\".\n"
                "Stay on that exact subject. Focus on its most recent, "
                "newsworthy developments. Only narrow to a sub-angle if the "
                "main story is already covered by the existing entries below.")
    else:
        task = ("No topic was given. Pick ONE specific, current topic for "
                "this section that is NOT already well covered by the "
                "existing entries below. Prefer something concrete (a named "
                "company, project type, regulation, technology or market "
                "move) over a broad theme.")

    raw, err = _llm(
        f"Today is {date.today():%d %B %Y}. "
        "You plan research for Technomak's internal executive digest. "
        "Technomak is an industrial/EPC company (oil & gas, construction, "
        "industrial automation) based in the UAE. You are planning the "
        f"'{label}' section.\n\n"
        "Respond ONLY with a JSON object, no markdown fences:\n"
        "{\"topic\": one-line specific topic, \"search_queries\": 2 to 4 "
        "web search queries}\n\n"
        "Query rules:\n"
        "- Each query must be concrete and answerable from public web "
        "pages: include names, places, industries or timeframes.\n"
        "- Queries must approach the topic from different angles; do not "
        "just restate the topic text as a query.\n"
        "- Target recent news: use the current or previous year in "
        "queries, not older years.\n"
        "- Do not include the word 'Technomak' unless the topic is "
        "specifically about Technomak.",
        f"{task}\n\nExisting entries in '{label}':\n{existing}",
        max_tokens=1200,
    )
    if err:
        return {"error": f"Decide Topic: {err}"}
    data = _parse_json_object(raw)
    if data is None:
        return {"error": "Decide Topic: the model returned malformed JSON."}

    new_topic = str(data.get("topic") or "").strip() or topic
    queries, seen = [], set()
    for q in data.get("search_queries") or []:
        q = " ".join(str(q).split())
        if q and q.lower() not in seen:
            seen.add(q.lower())
            queries.append(q)
    # Drop a query that is just the raw topic echoed back, if others exist.
    if topic and len(queries) > 1:
        queries = [q for q in queries if q.lower() != topic.lower()] or queries
    queries = queries[:4]
    if not new_topic or not queries:
        return {"error": "Decide Topic: the model did not return a topic "
                         "and search queries."}
    return {"topic": new_topic, "search_queries": queries}


# --- Node 2: research ------------------------------------------------------

def research(state: AgentState) -> dict:
    if _halted(state):
        return {}
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return {"error": "Research: TAVILY_API_KEY is not set, so the agent "
                         "can't search the web. Set it and restart the app."}

    per_query, failures = [], []
    for query in state.get("search_queries") or []:
        results, err = tavily_search(api_key, query, RESULTS_PER_QUERY)
        if err:
            failures.append(f"'{query}': {err}")
            continue
        per_query.append(results)

    if not per_query:
        return {"error": "Research: every Tavily search failed - "
                         + "; ".join(failures)}

    # Interleave queries (1st result of each, then 2nd of each...) so the
    # cap of 8 isn't filled entirely by the first query.
    sources, seen = [], set()
    for rank in range(RESULTS_PER_QUERY):
        for results in per_query:
            if rank >= len(results) or len(sources) >= MAX_SOURCES:
                continue
            r = results[rank] if isinstance(results[rank], dict) else {}
            url = str(r.get("url") or "").strip()
            dedupe_key = url.rstrip("/").lower()
            if not url or dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            sources.append({
                "title": " ".join(str(r.get("title") or url).split())[:200],
                "url": url,
                "snippet": " ".join(str(r.get("content") or "").split())[:500],
            })

    if not sources:
        return {"error": "Research: Tavily returned no results for any "
                         "search query. Try a different or broader topic."}
    out = {"raw_sources": sources}
    if failures:
        out["warnings"] = _warn(state, "Some searches failed: " + "; ".join(failures))
    return out


# --- Node 3: gather_db_context ---------------------------------------------

def gather_db_context(state: AgentState) -> dict:
    if _halted(state):
        return {}
    try:
        return {"db_context": _section_digest(state["section"])}
    except Exception as exc:  # sqlite errors etc.
        return {"error": f"Gather DB context: could not read entries ({exc})."}


# --- Node 4: draft ---------------------------------------------------------

def draft(state: AgentState) -> dict:
    if _halted(state):
        return {}
    label = _section_label(state["section"])
    tags = _allowed_tags()

    revise = ""
    fixes = [f for f in (state.get("critic_feedback"), state.get("human_feedback")) if f]
    if fixes and state.get("body"):
        revise = ("\n\n=== PREVIOUS DRAFT ===\n"
                  f"Subject: {state.get('subject', '')}\n"
                  f"Body: {state['body']}\n\n"
                  "Revise to address:\n" + "\n".join(fixes))
    elif fixes:
        revise = "\n\nRevise to address:\n" + "\n".join(fixes)

    raw, err = _llm(
        "You are an editor for Technomak's internal executive digest, "
        f"writing ONE entry for the '{label}' section. Technomak is an "
        "industrial/EPC company based in the UAE.\n\n"
        "STRICT SOURCING RULES:\n"
        "- Every factual claim must be traceable to the WEB SOURCES, the "
        "INTERNAL CONTEXT or the ADMIN FEEDBACK provided.\n"
        "- NEVER state a number, amount, percentage, name, company, place "
        "or date that does not appear in one of those. If a detail isn't "
        "there, leave it out - do not estimate or fill gaps.\n"
        "- Do not repeat what an internal entry already says, and do not "
        "contradict it. If a web source conflicts with an internal entry, "
        "say explicitly that the sources disagree.\n"
        "- Neutral reporting voice, no marketing language, no advice "
        "phrased as fact.\n\n"
        "Respond ONLY with a JSON object, no markdown fences:\n"
        "{\"subject\": short clear headline (max ~12 words), "
        "\"body\": 2-4 full sentences, "
        f"\"tag\": one of {'/'.join(tags)}}}",
        f"Today is {date.today():%d %B %Y}.\nTopic: {state.get('topic', '')}\n\n"
        f"{_evidence_block(state)}{revise}",
        max_tokens=2000,
    )
    if err:
        return {"error": f"Draft: {err}"}
    data = _parse_json_object(raw)
    if data is None:
        return {"error": "Draft: the model returned malformed JSON."}
    subject = " ".join(str(data.get("subject") or "").split())
    body = str(data.get("body") or "").strip()
    if not subject or not body:
        return {"error": "Draft: the model returned an empty subject or body."}
    tag = data.get("tag") if data.get("tag") in tags else "New"
    return {"subject": subject, "body": body, "tag": tag}


# --- Node 5: self_check (critic) -------------------------------------------

def self_check(state: AgentState) -> dict:
    if _halted(state):
        return {}
    raw, err = _llm(
        "You are a strict fact-checker. You receive a draft digest entry "
        "and the ONLY evidence it may rely on. Hunt specifically for "
        "unsupported claims: any number, amount, percentage, name, "
        "company, place, date or factual assertion in the draft that is "
        "not stated in the evidence, is stated differently there, or "
        "contradicts the internal context. Paraphrase and summary are "
        "fine; new facts are not. Do not comment on style.\n\n"
        "Respond ONLY with a JSON object, no markdown fences:\n"
        "{\"unsupported_claims\": [\"<quoted claim> - <why it is "
        "unsupported>\", ...]}  (an empty list if everything is supported)",
        f"=== DRAFT ===\nSubject: {state.get('subject', '')}\n"
        f"Body: {state.get('body', '')}\n\n{_evidence_block(state)}",
        max_tokens=1500,
    )
    data = _parse_json_object(raw) if not err else None
    if data is None or not isinstance(data.get("unsupported_claims"), list):
        reason = err or "malformed JSON from the model"
        return {"critic_feedback": "",
                "warnings": _warn(state, f"Self-check could not run ({reason}); "
                                         "this draft was NOT fact-checked.")}

    issues = [str(i).strip() for i in data["unsupported_claims"] if str(i).strip()]
    revision_count = state.get("revision_count", 0)
    if issues and revision_count < MAX_REVISIONS:
        return {"critic_feedback": "\n".join(f"- {i}" for i in issues),
                "revision_count": revision_count + 1}
    if issues:
        return {"critic_feedback": "",
                "warnings": _warn(state, "Self-check still flags these after "
                                         f"{MAX_REVISIONS} revisions - verify "
                                         "before publishing: " + "; ".join(issues))}
    return {"critic_feedback": ""}


def route_after_self_check(state: AgentState) -> str:
    """self_check leaves critic_feedback set only when it wants a revision.
    An error always goes forward, so a failed draft can't loop."""
    if state.get("error"):
        return "structure_output"
    return "draft" if state.get("critic_feedback") else "structure_output"


# --- Node 6: structure_output ----------------------------------------------

def structure_output(state: AgentState) -> dict:
    if _halted(state):
        return {"status": "error"}
    section = state.get("section")
    title = " ".join(str(state.get("subject") or "").split())[:160]
    body = str(state.get("body") or "").strip()
    tag = state.get("tag") if state.get("tag") in _allowed_tags() else "New"
    if section not in _deps.get("section_meta", {}) or not title or not body:
        return {"status": "error",
                "error": "Structure output: the draft is missing a section, "
                         "title or body."}
    return {"subject": title, "body": body, "tag": tag,
            "entry": {"section": section, "title": title, "body": body, "tag": tag},
            "status": "pending_review"}


# --- Graph -----------------------------------------------------------------

def build_graph(checkpointer=None):
    g = StateGraph(AgentState)
    g.add_node("decide_topic", decide_topic)
    g.add_node("research", research)
    g.add_node("gather_db_context", gather_db_context)
    g.add_node("draft", draft)
    g.add_node("self_check", self_check)
    g.add_node("structure_output", structure_output)

    g.add_edge(START, "decide_topic")
    g.add_edge("decide_topic", "research")
    g.add_edge("research", "gather_db_context")
    g.add_edge("gather_db_context", "draft")
    g.add_edge("draft", "self_check")
    g.add_conditional_edges("self_check", route_after_self_check,
                            {"draft": "draft", "structure_output": "structure_output"})
    g.add_edge("structure_output", END)
    return g.compile(checkpointer=checkpointer)


# The checkpointer only exists so resume_with_feedback can seed a thread
# mid-graph; each run gets its own thread, deleted when the run ends. The
# durable copy of a run lives in the app's pending_drafts table.
_checkpointer = MemorySaver()
graph = build_graph(_checkpointer)

# What a feedback round needs to re-enter at draft without re-running 1-3.
RESUME_KEYS = ("section", "topic", "search_queries", "raw_sources",
               "db_context", "subject", "body", "tag")


def _run(values, as_node=None):
    thread_id = uuid.uuid4().hex
    config = {"configurable": {"thread_id": thread_id}}
    try:
        if as_node:
            graph.update_state(config, values, as_node=as_node)
            return graph.invoke(None, config)
        return graph.invoke(values, config)
    finally:
        _checkpointer.delete_thread(thread_id)


def run_agent(section, topic=""):
    """Run the graph end to end from a trigger {section, topic}."""
    return _run({"section": section, "topic": (topic or "").strip(),
                 "revision_count": 0, "warnings": []})


def resume_with_feedback(saved_state, human_feedback):
    """Re-enter at draft with the admin's feedback. saved_state is a
    previous run's final state (or at least RESUME_KEYS of it)."""
    values = {k: saved_state[k] for k in RESUME_KEYS if k in saved_state}
    values.update(human_feedback=human_feedback.strip(), critic_feedback="",
                  revision_count=0, warnings=[], error=None, status="")
    return _run(values, as_node="gather_db_context")


if __name__ == "__main__":
    # Smoke test: python agent.py [section] [topic]
    # Imports the app for its helpers - fine here, since this path only runs
    # when agent.py is the entry point.
    import sys
    import technomak_app as app_module
    configure(app_module.call_llm, app_module.recent_entries_digest_text,
              app_module.SECTION_META, app_module._ALLOWED_TAGS)
    result = run_agent(sys.argv[1] if len(sys.argv) > 1 else "news",
                       sys.argv[2] if len(sys.argv) > 2 else "")
    print(json.dumps(result, indent=2))
