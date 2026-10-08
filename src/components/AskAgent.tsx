import { useEffect, useRef, useState } from "react";
import { askNewsAgent, type AskSource, type DetailLevel } from "../api";

// Floating "Ask about the news" chat. Collapsed: a round button bottom-right.
// Open: a small chat panel. The conversation id (and the messages, so a
// refresh doesn't blank the panel) live in sessionStorage; the backend keeps
// the real conversation state - history and already-found sources - under
// that id, which is what lets follow-ups skip a new web search.

const CONVERSATION_KEY = "technomak-ask-conversation";
const MESSAGES_KEY = "technomak-ask-messages";
const MAX_QUERY = 300;

const SUGGESTIONS = [
  "What are the latest ADNOC contract awards?",
  "Any recent news on EPC contractors in the UAE?",
  "What's happening with digital twins in oil & gas?",
];

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  keyPoints?: string[];
  sources?: AskSource[];
  topic?: string;
  detail?: DetailLevel;
  note?: string;
  error?: boolean;
}

function newId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return "id-" + Math.random().toString(36).slice(2) + Date.now().toString(36);
}

// sessionStorage can throw (private mode, blocked storage) - never let that
// break the chat.
function readSession<T>(key: string, fallback: T): T {
  try {
    const raw = sessionStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function writeSession(key: string, value: unknown): void {
  try {
    if (value === null) sessionStorage.removeItem(key);
    else sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage unavailable - the chat still works for this page view */
  }
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function SourceChips({ sources }: { sources: AskSource[] }) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 10 }}>
      {sources
        .filter((s) => /^https?:\/\//i.test(s.url))
        .map((s) => (
          <a
            key={s.url}
            href={s.url}
            target="_blank"
            rel="noopener noreferrer"
            title={s.title}
            style={{
              fontSize: 10.5,
              fontWeight: 600,
              color: "#145f76",
              background: "#e0f2fe",
              border: "1px solid #bae6fd",
              borderRadius: 999,
              padding: "3px 9px",
              maxWidth: 200,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {hostOf(s.url)}
          </a>
        ))}
    </div>
  );
}

function AssistantBubble({
  msg,
  busy,
  onMore,
}: {
  msg: ChatMessage;
  busy: boolean;
  onMore: (topic: string) => void;
}) {
  return (
    <div style={{ display: "flex", justifyContent: "flex-start" }}>
      <div
        style={{
          maxWidth: "88%",
          background: msg.error ? "#fee2e2" : "#f4f6f8",
          color: msg.error ? "#c0453a" : "#1c1f24",
          border: "1px solid " + (msg.error ? "#fecaca" : "#e6e9ed"),
          borderRadius: "14px 14px 14px 4px",
          padding: "10px 12px",
          fontSize: 13,
          lineHeight: 1.55,
        }}
      >
        <div style={{ whiteSpace: "pre-wrap" }}>{msg.text}</div>
        {msg.keyPoints && msg.keyPoints.length > 0 && (
          <ul style={{ margin: "8px 0 0", paddingLeft: 18, color: "#4a5058" }}>
            {msg.keyPoints.map((p, i) => (
              <li key={i} style={{ marginBottom: 3 }}>
                {p}
              </li>
            ))}
          </ul>
        )}
        {msg.note && (
          <div style={{ marginTop: 8, fontSize: 11, color: "#8c939c", fontStyle: "italic" }}>{msg.note}</div>
        )}
        {msg.sources && msg.sources.length > 0 && <SourceChips sources={msg.sources} />}
        {msg.topic && msg.detail === "short" && !msg.error && (
          <button
            type="button"
            disabled={busy}
            onClick={() => onMore(msg.topic as string)}
            style={{
              marginTop: 10,
              background: "none",
              border: "none",
              padding: 0,
              color: busy ? "#8c939c" : "#1787ac",
              fontSize: 11.5,
              fontWeight: 700,
              cursor: busy ? "default" : "pointer",
              fontFamily: "inherit",
            }}
          >
            Tell me more →
          </button>
        )}
      </div>
    </div>
  );
}

export default function AskAgent() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>(() => readSession(MESSAGES_KEY, []));
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    writeSession(MESSAGES_KEY, messages.slice(-40));
  }, [messages]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, busy, open]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  async function send(query: string, detail?: DetailLevel) {
    const q = query.trim();
    if (!q || busy) return;
    // First message of a conversation creates its id.
    let conversationId = readSession<string | null>(CONVERSATION_KEY, null);
    if (!conversationId) {
      conversationId = newId();
      writeSession(CONVERSATION_KEY, conversationId);
    }
    setMessages((m) => [...m, { id: newId(), role: "user", text: q }]);
    setInput("");
    setBusy(true);

    const result = await askNewsAgent({ conversation_id: conversationId, query: q, detail_level: detail });
    setBusy(false);
    if (!result.ok) {
      setMessages((m) => [...m, { id: newId(), role: "assistant", text: result.error, error: true }]);
      return;
    }
    const d = result.data;
    setMessages((m) => [
      ...m,
      {
        id: newId(),
        role: "assistant",
        text: d.answer || d.response,
        keyPoints: d.key_points,
        sources: d.sources,
        topic: d.topic || undefined,
        detail: d.detail_level,
        note: d.note || undefined,
      },
    ]);
  }

  function newChat() {
    writeSession(CONVERSATION_KEY, null);
    setMessages([]);
    setInput("");
    inputRef.current?.focus();
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        title="Ask about the news"
        aria-label="Ask about the news"
        style={{
          position: "fixed",
          right: 20,
          bottom: 20,
          zIndex: 210,
          display: "flex",
          alignItems: "center",
          gap: 8,
          background: "linear-gradient(135deg, #1787ac 0%, #145f76 100%)",
          color: "#fff",
          border: "none",
          borderRadius: 999,
          padding: "12px 18px",
          fontSize: 13,
          fontWeight: 700,
          fontFamily: "inherit",
          cursor: "pointer",
          boxShadow: "0 6px 20px rgba(23,135,172,0.35)",
        }}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z" strokeLinejoin="round" />
        </svg>
        Ask about the news
      </button>
    );
  }

  return (
    <div
      role="dialog"
      aria-label="Ask about the news"
      style={{
        position: "fixed",
        right: 16,
        bottom: 16,
        zIndex: 210,
        width: "min(380px, calc(100vw - 32px))",
        height: "min(560px, calc(100vh - 32px))",
        background: "#fff",
        border: "1px solid #dfe3e8",
        borderRadius: 16,
        boxShadow: "0 12px 40px rgba(20,30,40,0.18)",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        fontFamily: "'Poppins', sans-serif",
      }}
    >
      <div
        style={{
          background: "linear-gradient(135deg, #1787ac 0%, #145f76 100%)",
          color: "#fff",
          padding: "12px 14px",
          display: "flex",
          alignItems: "center",
          gap: 10,
        }}
      >
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 14, fontWeight: 700 }}>Ask about the news</div>
          <div style={{ fontSize: 10.5, opacity: 0.85 }}>Live web research · answers cite their sources</div>
        </div>
        {messages.length > 0 && (
          <button type="button" onClick={newChat} disabled={busy} style={headerBtn} title="Start a new conversation">
            New chat
          </button>
        )}
        <button type="button" onClick={() => setOpen(false)} style={headerBtn} aria-label="Close">
          ✕
        </button>
      </div>

      <div ref={scrollRef} style={{ flex: 1, overflowY: "auto", padding: 14, display: "flex", flexDirection: "column", gap: 10 }}>
        {messages.length === 0 && (
          <div style={{ fontSize: 12.5, color: "#4a5058", lineHeight: 1.6 }}>
            Ask a question about industry news and I'll search the web and summarise what I find, with sources.
            <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 12 }}>
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => send(s)}
                  style={{
                    textAlign: "left",
                    background: "#f4f6f8",
                    border: "1px solid #e6e9ed",
                    borderRadius: 10,
                    padding: "8px 10px",
                    fontSize: 12,
                    color: "#145f76",
                    cursor: "pointer",
                    fontFamily: "inherit",
                  }}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m) =>
          m.role === "user" ? (
            <div key={m.id} style={{ display: "flex", justifyContent: "flex-end" }}>
              <div
                style={{
                  maxWidth: "80%",
                  background: "#1787ac",
                  color: "#fff",
                  borderRadius: "14px 14px 4px 14px",
                  padding: "8px 12px",
                  fontSize: 13,
                  lineHeight: 1.5,
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                }}
              >
                {m.text}
              </div>
            </div>
          ) : (
            <AssistantBubble key={m.id} msg={m} busy={busy} onMore={(topic) => send(`Tell me more about ${topic}`, "detailed")} />
          )
        )}
        {busy && (
          <div style={{ fontSize: 12, color: "#8c939c", fontStyle: "italic" }}>Researching… this can take up to a minute.</div>
        )}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
        style={{ borderTop: "1px solid #dfe3e8", padding: 10, display: "flex", gap: 8, alignItems: "flex-end" }}
      >
        <textarea
          ref={inputRef}
          value={input}
          maxLength={MAX_QUERY}
          rows={2}
          placeholder="Ask about a company, project or trend…"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send(input);
            }
          }}
          style={{
            flex: 1,
            resize: "none",
            border: "1px solid #dfe3e8",
            borderRadius: 10,
            padding: "8px 10px",
            fontSize: 13,
            fontFamily: "inherit",
            color: "#1c1f24",
            outline: "none",
          }}
        />
        <button
          type="submit"
          disabled={busy || !input.trim()}
          style={{
            background: busy || !input.trim() ? "#9cc9d8" : "#1787ac",
            color: "#fff",
            border: "none",
            borderRadius: 10,
            padding: "10px 14px",
            fontSize: 13,
            fontWeight: 700,
            fontFamily: "inherit",
            cursor: busy || !input.trim() ? "default" : "pointer",
          }}
        >
          Send
        </button>
      </form>
    </div>
  );
}

const headerBtn = {
  background: "rgba(255,255,255,0.18)",
  color: "#fff",
  border: "none",
  borderRadius: 8,
  padding: "5px 9px",
  fontSize: 11.5,
  fontWeight: 700,
  cursor: "pointer",
  fontFamily: "inherit",
} as const;
