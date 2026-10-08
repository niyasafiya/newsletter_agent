// Talks to the Flask backend (technomak_app.py) and adapts its response
// shape into the exact `Entry` shape the existing UI components expect.
// No component in App.tsx needs to know this data used to be hardcoded.

import { setEntries, type Entry, type SectionName, type Tag } from "./data";

interface BackendEntry {
  id: number;
  title: string;
  body: string;
  tag: string;
  date: string; // "2026-09-16"
  source: string;
  publisher: string;
  image: string | null;
}

interface BackendSection {
  label: string;
  entries: BackendEntry[];
}

type BackendSections = Record<string, BackendSection>;

export interface LiveStats {
  totalUpdates: number;
  sectionCount: number;
  importedCount: number;
  lastGenerated: string;
}

export interface LiveSummary {
  content: string;
  generated: string;
  mode: string;
}

function formatDate(iso: string): string {
  // "2026-09-16" -> "Sep 16, 2026", matching the style already used
  // throughout the original mock data ("Sep 12, 2026").
  const d = new Date(iso + "T00:00:00");
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function toEntry(sectionLabel: string, be: BackendEntry): Entry {
  // Entries carry either a bare filename (uploaded through the admin
  // console, served from Flask's /media/<name>) or a full external URL
  // (e.g. the original Figma demo content's Unsplash photos). Only the
  // former needs the /media/ prefix - an absolute URL is used as-is.
  const image = be.image
    ? /^https?:\/\//i.test(be.image)
      ? be.image
      : `/media/${be.image}`
    : undefined;

  return {
    id: String(be.id),
    section: sectionLabel as SectionName,
    title: be.title,
    body: be.body,
    tag: be.tag as Tag,
    date: formatDate(be.date),
    publisher: be.publisher,
    image,
  };
}

/** Fetches every section from the backend, flattens it into Entry[], and
 * pushes it into the live `entries` store. Also returns the raw sections
 * payload and derived stats so the caller can populate the stat tiles. */
export async function fetchLiveEntries(): Promise<{
  ok: boolean;
  stats: LiveStats;
}> {
  try {
    const res = await fetch("/api/v1/sections");
    if (!res.ok) throw new Error(`sections request failed: ${res.status}`);
    const data: BackendSections = await res.json();

    const flat: Entry[] = [];
    let imported = 0;
    for (const section of Object.values(data)) {
      for (const be of section.entries) {
        flat.push(toEntry(section.label, be));
        if (be.source !== "seed") imported += 1;
      }
    }
    // Newest first, matching how the original mock data was ordered.
    flat.sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));
    setEntries(flat);

    return {
      ok: true,
      stats: {
        totalUpdates: flat.length,
        sectionCount: Object.keys(data).length,
        importedCount: imported,
        lastGenerated: new Date().toLocaleDateString("en-US", { month: "short", year: "numeric" }),
      },
    };
  } catch {
    return {
      ok: false,
      stats: { totalUpdates: 0, sectionCount: 0, importedCount: 0, lastGenerated: "" },
    };
  }
}

/** The AI-generated (or rule-based) executive summary, if one has been
 * published from the admin console. Returns null if none exists yet. */
export async function fetchLiveSummary(): Promise<LiveSummary | null> {
  try {
    const res = await fetch("/api/v1/summary");
    if (!res.ok) return null;
    const data = await res.json();
    return data.summary ?? null;
  } catch {
    return null;
  }
}

/** Simple client-side search over whatever is already loaded into
 * `entries` - title, body and tag, case-insensitive. Good enough for a
 * digest of this size; avoids a network round-trip per keystroke. */
export function searchEntries(all: Entry[], query: string): Entry[] {
  const q = query.trim().toLowerCase();
  if (q.length < 2) return [];
  return all.filter(
    (e) =>
      e.title.toLowerCase().includes(q) ||
      e.body.toLowerCase().includes(q) ||
      e.tag.toLowerCase().includes(q) ||
      e.section.toLowerCase().includes(q)
  );
}

// ─── "Ask about the news" chat (reader_agent.py via /api/v1/ask) ────────────

export type DetailLevel = "short" | "detailed";

export interface AskSource {
  title: string;
  url: string;
  published_date: string;
}

export interface AskRequest {
  conversation_id?: string;
  query: string;
  detail_level?: DetailLevel;
}

export interface AskResponse {
  conversation_id: string;
  response: string; // full plain-text reply (answer + points + sources)
  answer: string; // just the conversational part
  key_points: string[];
  sources: AskSource[];
  topic: string;
  detail_level: DetailLevel;
  note: string; // e.g. "couldn't double-check these points" - usually ""
}

/** One chat turn. The backend researches the web live, so this can take
 * 10-60 seconds. Never throws: returns ok=false with a readable error. */
export async function askNewsAgent(
  req: AskRequest
): Promise<{ ok: true; data: AskResponse } | { ok: false; error: string }> {
  try {
    const res = await fetch("/api/v1/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    const data = await res.json().catch(() => null);
    if (!res.ok || !data || data.error) {
      return { ok: false, error: data?.error || `The assistant request failed (${res.status}).` };
    }
    return { ok: true, data: data as AskResponse };
  } catch {
    return { ok: false, error: "Couldn't reach the news assistant. Check your connection and try again." };
  }
}
