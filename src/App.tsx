import { useState, useEffect } from "react";
import { fetchLiveEntries, fetchLiveSummary, searchEntries, type LiveStats, type LiveSummary } from "./api";
import AskAgent from "./components/AskAgent";
import {
  entries,
  sections,
  sectionAccents,
  tagColor,
  type Entry,
  type SectionName,
} from "./data";

type View =
  | { kind: "home" }
  | { kind: "section"; section: SectionName }
  | { kind: "story"; entry: Entry }
  | { kind: "influencer" };

// ─── Tiny helpers ───────────────────────────────────────────────────────────

function Tag({ tag }: { tag: string }) {
  const c = tagColor(tag);
  return (
    <span
      style={{
        background: c.bg,
        color: c.text,
        fontSize: 9,
        fontWeight: 800,
        letterSpacing: "0.12em",
        textTransform: "uppercase",
        padding: "2px 7px",
        borderRadius: 2,
      }}
    >
      {tag}
    </span>
  );
}

// ─── Card ────────────────────────────────────────────────────────────────────

function Card({
  entry,
  wide = false,
  accent,
  onStory,
}: {
  entry: Entry;
  wide?: boolean;
  accent: string;
  onStory: (e: Entry) => void;
}) {
  const [hovered, setHovered] = useState(false);

  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onClick={() => onStory(entry)}
      style={{
        borderTop: "2px solid #1c1f24",
        background: hovered ? "#f8f9fa" : "#fff",
        cursor: "pointer",
        display: "flex",
        flexDirection: "column",
        transition: "background 0.15s",
        gridColumn: wide ? "span 2" : undefined,
      }}
    >
      {/* Image strip */}
      <div
        style={{
          height: wide ? 190 : 150,
          overflow: "hidden",
          flexShrink: 0,
          background: "#e8f4f8",
        }}
      >
        {entry.image ? (
          <img
            src={entry.image}
            alt={entry.title}
            style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
          />
        ) : (
          <div
            style={{
              width: "100%",
              height: "100%",
              background: `linear-gradient(135deg, #e8f4f8 0%, #d1eaf2 100%)`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <svg width="40" height="40" viewBox="0 0 40 40" fill="none">
              <rect width="40" height="40" rx="4" fill={accent} fillOpacity="0.12" />
              <path d="M8 28l8-8 6 6 5-5 7 7" stroke={accent} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              <circle cx="14" cy="16" r="4" fill={accent} fillOpacity="0.3" />
            </svg>
          </div>
        )}
      </div>

      {/* Meta row */}
      <div
        style={{
          padding: "10px 14px 0",
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <Tag tag={entry.tag} />
        <div
          style={{
            flex: 1,
            height: 1,
            background: "#dfe3e8",
          }}
        />
        <span
          style={{
            fontSize: 10,
            color: "#8c939c",
            fontWeight: 500,
            whiteSpace: "nowrap",
          }}
        >
          {entry.date}
        </span>
      </div>

      {/* Title */}
      <div
        style={{
          padding: "8px 14px 6px",
          fontSize: wide ? 20 : 15,
          fontWeight: 800,
          letterSpacing: "-0.015em",
          color: "#1c1f24",
          lineHeight: 1.25,
        }}
      >
        {entry.title}
      </div>

      {/* Excerpt */}
      <div
        style={{
          padding: "0 14px 12px",
          fontSize: 12,
          color: "#4a5058",
          lineHeight: 1.6,
          flex: 1,
          display: "-webkit-box",
          WebkitLineClamp: 3,
          WebkitBoxOrient: "vertical",
          overflow: "hidden",
        }}
      >
        {entry.body}
      </div>

      {/* Footer */}
      <div
        style={{
          borderTop: "1px solid #dfe3e8",
          padding: "8px 14px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <span style={{ fontSize: 10, fontWeight: 600, color: "#8c939c" }}>
          {entry.publisher}
        </span>
        <span
          style={{
            fontSize: 10,
            fontWeight: 800,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: accent,
            transform: hovered ? "translateX(3px)" : "translateX(0)",
            transition: "transform 0.15s",
          }}
        >
          Read more →
        </span>
      </div>
    </div>
  );
}

// ─── Lead Panel ──────────────────────────────────────────────────────────────

function LeadPanel({
  entry,
  accent,
  onStory,
}: {
  entry: Entry;
  accent: string;
  onStory: (e: Entry) => void;
}) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 1fr",
        marginBottom: 24,
      }}
    >
      {/* Left — teal */}
      <div
        style={{
          background: `linear-gradient(135deg, #1787ac 0%, #145f76 100%)`,
          padding: "28px 32px",
          display: "flex",
          flexDirection: "column",
          gap: 14,
        }}
      >
        <div
          style={{
            fontSize: 11,
            fontWeight: 800,
            letterSpacing: "0.14em",
            textTransform: "uppercase",
            color: "rgba(255,255,255,0.7)",
          }}
        >
          Top News
        </div>
        <div
          style={{
            fontSize: 28,
            fontWeight: 800,
            color: "#fff",
            lineHeight: 1.2,
            letterSpacing: "-0.02em",
          }}
        >
          {entry.title}
        </div>
        <div
          style={{
            fontSize: 13,
            color: "rgba(255,255,255,0.75)",
            lineHeight: 1.65,
            flex: 1,
          }}
        >
          {entry.body.slice(0, 200)}…
        </div>
        <button
          onClick={() => onStory(entry)}
          style={{
            alignSelf: "flex-start",
            background: "transparent",
            border: "none",
            color: "rgba(255,255,255,0.9)",
            fontSize: 10,
            fontWeight: 800,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            cursor: "pointer",
            padding: 0,
            fontFamily: "inherit",
          }}
        >
          {entry.publisher} · {entry.date} · Read the full update →
        </button>
      </div>

      {/* Right — bordered */}
      <div
        style={{
          border: "1px solid #dfe3e8",
          borderLeft: "none",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <div style={{ flex: 1, minHeight: 200, overflow: "hidden", background: "#e8f4f8" }}>
          {entry.image ? (
            <img
              src={entry.image}
              alt={entry.title}
              style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
            />
          ) : (
            <div
              style={{
                width: "100%",
                height: "100%",
                background: `linear-gradient(135deg, #e8f4f8 0%, #c8e4ee 100%)`,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <svg width="56" height="56" viewBox="0 0 56 56" fill="none">
                <rect width="56" height="56" rx="6" fill={accent} fillOpacity="0.1" />
                <path d="M10 40l12-12 8 8 7-7 9 11" stroke={accent} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                <circle cx="20" cy="22" r="5" fill={accent} fillOpacity="0.25" />
              </svg>
            </div>
          )}
        </div>
        <div style={{ padding: "16px 20px" }}>
          <Tag tag={entry.tag} />
          <div
            style={{
              marginTop: 10,
              fontSize: 12,
              color: "#4a5058",
              lineHeight: 1.6,
            }}
          >
            Open the full update for complete detail on this story.
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Section Block ────────────────────────────────────────────────────────────

function SectionBlock({
  section,
  onSection,
  onStory,
}: {
  section: SectionName;
  onSection: (s: SectionName) => void;
  onStory: (e: Entry) => void;
}) {
  const accent = sectionAccents[section];
  const sectionEntries = entries.filter((e) => e.section === section);
  const lead = sectionEntries[0];
  const cards = sectionEntries.slice(1);
  const remaining = Math.max(0, sectionEntries.length - 4);

  return (
    <div style={{ marginBottom: 60 }}>
      {/* Section header row */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 16,
          marginBottom: 16,
          paddingBottom: 12,
        }}
      >
        <button
          onClick={() => onSection(section)}
          style={{
            background: "none",
            border: "none",
            fontSize: 22,
            fontWeight: 800,
            letterSpacing: "-0.02em",
            color: "#1c1f24",
            cursor: "pointer",
            fontFamily: "inherit",
            padding: 0,
            whiteSpace: "nowrap",
          }}
        >
          {section}
        </button>
        <div style={{ flex: 1, height: 3, background: accent, borderRadius: 1 }} />
        <span
          style={{
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            color: "#8c939c",
            whiteSpace: "nowrap",
          }}
        >
          {sectionEntries.length} updates
        </span>
      </div>

      {/* Lead panel */}
      {lead && <LeadPanel entry={lead} accent={accent} onStory={onStory} />}

      {/* Card grid */}
      {cards.length > 0 && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(3, 1fr)",
            gap: 20,
            marginBottom: 16,
          }}
        >
          {cards.slice(0, 3).map((e, i) => (
            <Card
              key={e.id}
              entry={e}
              wide={i === 0 && cards.length >= 2}
              accent={accent}
              onStory={onStory}
            />
          ))}
        </div>
      )}

      {/* Read all footer */}
      <div
        style={{
          borderTop: "2px solid #1c1f24",
          paddingTop: 10,
          display: "flex",
          alignItems: "center",
          gap: 12,
        }}
      >
        <button
          onClick={() => onSection(section)}
          style={{
            background: "none",
            border: "none",
            fontSize: 10,
            fontWeight: 800,
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            color: accent,
            cursor: "pointer",
            fontFamily: "inherit",
            padding: 0,
            whiteSpace: "nowrap",
          }}
        >
          Read all {section} updates →
        </button>
        <div style={{ flex: 1, height: 1, background: "#dfe3e8" }} />
        {remaining > 0 && (
          <span
            style={{
              fontSize: 10,
              fontWeight: 600,
              color: "#8c939c",
              whiteSpace: "nowrap",
            }}
          >
            +{remaining} more
          </span>
        )}
      </div>
    </div>
  );
}

// ─── Stat Tile ────────────────────────────────────────────────────────────────

function StatTile({
  value,
  label,
  variant,
}: {
  value: string;
  label: string;
  variant: "a" | "b";
}) {
  const bg =
    variant === "a"
      ? "linear-gradient(135deg, #1787ac 0%, #145f76 100%)"
      : "linear-gradient(135deg, #2AA3B8 0%, #1a7686 100%)";

  return (
    <div
      style={{
        background: bg,
        padding: "24px 20px",
        flex: 1,
        display: "flex",
        flexDirection: "column",
        gap: 4,
      }}
    >
      <div
        style={{
          fontSize: 30,
          fontWeight: 900,
          color: "#fff",
          letterSpacing: "-0.02em",
          lineHeight: 1,
        }}
      >
        {value}
      </div>
      <div
        style={{
          fontSize: 10,
          fontWeight: 600,
          color: "rgba(255,255,255,0.7)",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
        }}
      >
        {label}
      </div>
    </div>
  );
}

// ─── Nav dot ─────────────────────────────────────────────────────────────────

function NavDot({ section, onSection }: { section: SectionName; onSection: (s: SectionName) => void }) {
  const accent = sectionAccents[section];
  return (
    <button
      onClick={() => onSection(section)}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 5,
        background: "none",
        border: "none",
        cursor: "pointer",
        fontFamily: "inherit",
        fontSize: 9,
        fontWeight: 700,
        letterSpacing: "0.08em",
        textTransform: "uppercase",
        color: "#4a5058",
        padding: "0 4px",
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: accent,
          flexShrink: 0,
        }}
      />
      {section}
    </button>
  );
}

// ─── Pages ────────────────────────────────────────────────────────────────────

function HomePage({
  onSection,
  onStory,
  stats,
  summary,
}: {
  onSection: (s: SectionName) => void;
  onStory: (e: Entry) => void;
  stats: LiveStats;
  summary: LiveSummary | null;
}) {
  const totalUpdates = entries.length;
  const [query, setQuery] = useState("");
  const results = searchEntries(entries, query);

  return (
    <>
      {/* Header */}
      <header
        style={{
          position: "sticky",
          top: 0,
          zIndex: 100,
          background: "#fff",
          borderBottom: "1px solid #dfe3e8",
          display: "flex",
          alignItems: "center",
          padding: "0 40px",
          height: 52,
          gap: 32,
        }}
      >
        <div
          style={{
            fontSize: 14,
            fontWeight: 800,
            letterSpacing: "-0.01em",
            color: "#1c1f24",
            whiteSpace: "nowrap",
          }}
        >
          technomak
          <span style={{ color: "#1787ac" }}>.digest</span>
        </div>
        <nav
          style={{
            flex: 1,
            display: "flex",
            gap: 4,
            alignItems: "center",
            justifyContent: "center",
            flexWrap: "wrap",
          }}
        >
          {sections.map((s) => (
            <NavDot key={s} section={s} onSection={onSection} />
          ))}
        </nav>
        <button
          onClick={() => { window.location.href = "/login"; }}
          style={{
            background: "#1c1f24",
            color: "#fff",
            border: "none",
            borderRadius: 999,
            padding: "6px 16px",
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            cursor: "pointer",
            fontFamily: "inherit",
            whiteSpace: "nowrap",
          }}
        >
          Admin
        </button>
      </header>

      {/* Hero block */}
      <div style={{ padding: "52px 40px 40px", maxWidth: 1100, margin: "0 auto" }}>
        {/* Edition row */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: 16,
          }}
        >
          <span style={{ fontSize: 11, color: "#8c939c", fontWeight: 500 }}>
            Quarter 3 Edition · September 2026
          </span>
          <span
            style={{
              background: "#1787ac",
              color: "#fff",
              fontSize: 9,
              fontWeight: 800,
              letterSpacing: "0.14em",
              textTransform: "uppercase",
              padding: "4px 10px",
              borderRadius: 2,
            }}
          >
            TECHNOMAK
          </span>
        </div>

        {/* Masthead */}
        <div
          style={{
            fontSize: "clamp(52px, 10vw, 96px)",
            fontWeight: 900,
            color: "#1787ac",
            letterSpacing: "-0.03em",
            lineHeight: 0.9,
            marginBottom: 12,
            textTransform: "uppercase",
          }}
        >
          NEWSLETTER
        </div>

        {/* Subtitle row */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 20,
            marginBottom: 32,
          }}
        >
          <span
            style={{
              fontSize: 13,
              fontWeight: 600,
              letterSpacing: "0.34em",
              textTransform: "uppercase",
              color: "#4a5058",
              whiteSpace: "nowrap",
            }}
          >
            EXECUTIVE DIGEST
          </span>
          <div
            style={{
              flex: 1,
              height: 1,
              background: "linear-gradient(to right, #dfe3e8, transparent)",
            }}
          />
        </div>

        {/* Search */}
        <div style={{ position: "relative", maxWidth: 580, marginBottom: 40 }}>
          <svg
            style={{
              position: "absolute",
              left: 14,
              top: "50%",
              transform: "translateY(-50%)",
              color: "#8c939c",
            }}
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <circle cx="11" cy="11" r="8" />
            <path d="m21 21-4.35-4.35" />
          </svg>
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search all updates — projects, competitors, risks…"
            style={{
              width: "100%",
              border: "1px solid #dfe3e8",
              borderRadius: 3,
              padding: "11px 14px 11px 40px",
              fontSize: 13,
              fontFamily: "inherit",
              color: "#4a5058",
              outline: "none",
            }}
          />
        </div>

        {/* Stat tiles */}
        <div style={{ display: "flex", gap: 0, marginBottom: 56 }}>
          <StatTile value={String(totalUpdates)} label="Total Updates" variant="a" />
          <StatTile value={String(stats.sectionCount || 8)} label="Tracked Sections" variant="b" />
          <StatTile value={String(stats.importedCount)} label="Imported via Upload / URL" variant="a" />
          <StatTile value={stats.lastGenerated || "—"} label="Last Generated" variant="b" />
        </div>

        {/* AI Executive Summary panel + section blocks - hidden while a
            search is active, so the results grid below takes their place. */}
        {query.trim().length < 2 && (
          <>
        <div
          style={{
            background: "linear-gradient(135deg, #e8f6fb 0%, #d5eef7 100%)",
            border: "1px solid #b8dded",
            borderRadius: 4,
            padding: "20px 24px",
            marginBottom: 52,
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#1787ac" strokeWidth="2" strokeLinecap="round">
                <path d="M12 2L2 7l10 5 10-5-10-5z" />
                <path d="M2 17l10 5 10-5" />
                <path d="M2 12l10 5 10-5" />
              </svg>
              <span style={{ fontSize: 12, fontWeight: 700, color: "#1787ac", letterSpacing: "0.06em", textTransform: "uppercase" }}>
                Executive Summary
              </span>
            </div>
            <span style={{ fontSize: 9, color: "#8c939c", fontWeight: 500 }}>
              {summary ? `Generated ${summary.generated}` : "Generated Sep 17, 2026"}
            </span>
          </div>
          <ul style={{ margin: 0, padding: "0 0 0 16px", display: "flex", flexDirection: "column", gap: 6 }}>
            {(summary
              ? summary.content.split("\n").filter((l) => l.trim())
              : [
                  "Q3 pipeline reached a record €82M — strongest quarter in company history, with APAC expansion in LOI stage.",
                  "TM-9000 launched to GA; NPS climbed to 72 and field SLA breaches fell 61% following process redesign.",
                  "Nexora's AI acquisition and VoltEdge pricing moves introduce competitive pressure; monitoring recommended.",
                  "Dr. Priya Nair appointed CTO effective 1 October — engineering academy cohort 4 graduated 28 engineers.",
                ]
            ).map((line, i) => (
              <li key={i} style={{ fontSize: 12.5, color: "#1c1f24", lineHeight: 1.6 }}>
                {line}
              </li>
            ))}
          </ul>
        </div>

        {/* Section blocks */}
        {sections.map((s) => (
          <SectionBlock key={s} section={s} onSection={onSection} onStory={onStory} />
        ))}
          </>
        )}

        {/* Search results - same Card component the rest of the app uses,
            just filtered instead of grouped by section. */}
        {query.trim().length >= 2 && (
          <div style={{ marginBottom: 52 }}>
            <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 20 }}>
              <div style={{ fontSize: 20, fontWeight: 800, color: "#1c1f24" }}>Search results</div>
              <span style={{ fontSize: 11, color: "#8c939c" }}>
                {results.length} match{results.length !== 1 ? "es" : ""} for "{query.trim()}"
              </span>
            </div>
            {results.length === 0 ? (
              <div style={{ padding: "48px 0", textAlign: "center", color: "#8c939c", fontSize: 13 }}>
                No updates match that search.
              </div>
            ) : (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 20 }}>
                {results.map((r) => (
                  <Card key={r.id} entry={r} accent={sectionAccents[r.section]} onStory={onStory} />
                ))}
              </div>
            )}
          </div>
        )}
      </div>


      {/* Footer */}
      <footer
        style={{
          background: "#1c1f24",
          padding: "18px 40px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <span style={{ fontSize: 10, color: "#8c939c", fontWeight: 500 }}>
          CONFIDENTIAL — For internal executive circulation only. Not for external distribution. © Technomak 2026
        </span>
        <button
          onClick={() => { window.location.href = "/login"; }}
          style={{
            background: "none",
            border: "none",
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            color: "#1787ac",
            cursor: "pointer",
            fontFamily: "inherit",
          }}
        >
          Admin console →
        </button>
      </footer>
    </>
  );
}

function SectionPage({
  section,
  onBack,
  onStory,
}: {
  section: SectionName;
  onBack: () => void;
  onStory: (e: Entry) => void;
}) {
  const accent = sectionAccents[section];
  const sectionEntries = entries.filter((e) => e.section === section);

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto", padding: "48px 40px" }}>
      {/* Back */}
      <button
        onClick={onBack}
        style={{
          background: "none",
          border: "none",
          borderBottom: "1px solid #1c1f24",
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: "0.1em",
          textTransform: "uppercase",
          color: "#1c1f24",
          cursor: "pointer",
          fontFamily: "inherit",
          padding: "0 0 2px",
          marginBottom: 40,
        }}
      >
        ← Back to digest
      </button>

      {/* Section heading */}
      <div style={{ borderTop: `3px solid ${accent}`, paddingTop: 16, marginBottom: 6 }}>
        <div
          style={{
            fontSize: "clamp(26px, 4vw, 38px)",
            fontWeight: 800,
            color: "#1c1f24",
            letterSpacing: "-0.02em",
          }}
        >
          {section}
        </div>
      </div>
      <div style={{ fontSize: 11, color: "#8c939c", fontWeight: 500, marginBottom: 36 }}>
        {sectionEntries.length} updates — full archive
      </div>

      {/* Card grid */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
          gap: 20,
        }}
      >
        {sectionEntries.map((e) => (
          <Card key={e.id} entry={e} accent={accent} onStory={onStory} />
        ))}
      </div>
    </div>
  );
}

function StoryPage({
  entry,
  onBack,
  onStory,
}: {
  entry: Entry;
  onBack: () => void;
  onStory: (e: Entry) => void;
}) {
  const accent = sectionAccents[entry.section];
  const related = entries
    .filter((e) => e.section === entry.section && e.id !== entry.id)
    .slice(0, 3);

  return (
    <div style={{ maxWidth: 860, margin: "0 auto", padding: "48px 40px" }}>
      {/* Back */}
      <button
        onClick={onBack}
        style={{
          background: "none",
          border: "none",
          borderBottom: "1px solid #1c1f24",
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: "0.1em",
          textTransform: "uppercase",
          color: "#1c1f24",
          cursor: "pointer",
          fontFamily: "inherit",
          padding: "0 0 2px",
          marginBottom: 40,
        }}
      >
        ← Back to digest
      </button>

      {/* Eyebrow */}
      <div
        style={{
          fontSize: 10,
          fontWeight: 800,
          letterSpacing: "0.14em",
          textTransform: "uppercase",
          color: accent,
          marginBottom: 12,
        }}
      >
        {entry.section} · {entry.tag}
      </div>

      {/* Title */}
      <div
        style={{
          fontSize: "clamp(24px, 4vw, 40px)",
          fontWeight: 800,
          color: "#1c1f24",
          letterSpacing: "-0.02em",
          lineHeight: 1.15,
          marginBottom: 20,
        }}
      >
        {entry.title}
      </div>

      {/* Byline */}
      <div
        style={{
          fontSize: 11,
          color: "#8c939c",
          fontWeight: 500,
          paddingBottom: 16,
          borderBottom: "1px solid #dfe3e8",
          marginBottom: 32,
        }}
      >
        {entry.publisher} · {entry.date} · Internal update
      </div>

      {/* Body */}
      <div
        style={{
          maxWidth: 660,
          fontSize: 16,
          color: "#4a5058",
          lineHeight: 1.75,
          marginBottom: 56,
        }}
      >
        {entry.body}
      </div>

      {/* Related */}
      {related.length > 0 && (
        <div>
          <div
            style={{
              borderTop: "2px solid #1c1f24",
              paddingTop: 14,
              marginBottom: 20,
            }}
          >
            <span
              style={{
                fontSize: 10,
                fontWeight: 800,
                letterSpacing: "0.12em",
                textTransform: "uppercase",
                color: "#8c939c",
              }}
            >
              More in {entry.section}
            </span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {related.map((r) => (
              <button
                key={r.id}
                onClick={() => onStory(r)}
                style={{
                  background: "none",
                  border: "none",
                  textAlign: "left",
                  cursor: "pointer",
                  fontFamily: "inherit",
                  padding: 0,
                  display: "flex",
                  flexDirection: "column",
                  gap: 2,
                  borderBottom: "1px solid #dfe3e8",
                  paddingBottom: 16,
                }}
              >
                <span
                  style={{
                    fontSize: 15,
                    fontWeight: 700,
                    color: "#1c1f24",
                    letterSpacing: "-0.01em",
                  }}
                >
                  {r.title}
                </span>
                <span style={{ fontSize: 11, color: "#8c939c" }}>
                  {r.publisher} · {r.date}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── AI Influencer Page ───────────────────────────────────────────────────────

function InfluencerPage({ onBack }: { onBack: () => void }) {
  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        background: "linear-gradient(135deg, #e8f6fb 0%, #d5eef7 60%, #fff 100%)",
        padding: 40,
        fontFamily: "'Poppins', sans-serif",
      }}
    >
      <button
        onClick={onBack}
        style={{
          position: "absolute",
          top: 32,
          left: 40,
          background: "none",
          border: "none",
          borderBottom: "1px solid #1c1f24",
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: "0.1em",
          textTransform: "uppercase",
          color: "#1c1f24",
          cursor: "pointer",
          fontFamily: "inherit",
          padding: "0 0 2px",
        }}
      >
        ← Back to digest
      </button>

      {/* Avatar placeholder */}
      <div
        style={{
          width: 120,
          height: 120,
          borderRadius: "50%",
          background: "linear-gradient(135deg, #1787ac 0%, #145f76 100%)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          marginBottom: 28,
          boxShadow: "0 8px 32px rgba(23,135,172,0.25)",
        }}
      >
        <svg width="52" height="52" viewBox="0 0 52 52" fill="none">
          <circle cx="26" cy="20" r="10" fill="rgba(255,255,255,0.9)" />
          <path d="M6 46c0-11 9-18 20-18s20 7 20 18" stroke="rgba(255,255,255,0.9)" strokeWidth="3" strokeLinecap="round" />
        </svg>
      </div>

      <div
        style={{
          fontSize: 11,
          fontWeight: 800,
          letterSpacing: "0.2em",
          textTransform: "uppercase",
          color: "#1787ac",
          marginBottom: 10,
        }}
      >
        Technomak AI
      </div>
      <div
        style={{
          fontSize: 32,
          fontWeight: 900,
          color: "#1c1f24",
          letterSpacing: "-0.02em",
          marginBottom: 12,
          textAlign: "center",
        }}
      >
        AI Influencer
      </div>
      <div
        style={{
          fontSize: 14,
          color: "#8c939c",
          fontWeight: 500,
          maxWidth: 400,
          textAlign: "center",
          lineHeight: 1.65,
          marginBottom: 40,
        }}
      >
        Your AI-powered executive companion is coming soon. Integration in progress.
      </div>

      {/* Placeholder content area */}
      <div
        style={{
          width: "100%",
          maxWidth: 560,
          border: "2px dashed #dfe3e8",
          borderRadius: 6,
          padding: "48px 32px",
          textAlign: "center",
          color: "#8c939c",
          fontSize: 12,
          fontWeight: 500,
        }}
      >
        AI Influencer integration will be embedded here
      </div>
    </div>
  );
}

// ─── Floating Influencer Button ───────────────────────────────────────────────

function InfluencerButton({ onClick }: { onClick: () => void }) {
  const [hovered, setHovered] = useState(false);

  return (
    <button
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      title="AI Influencer"
      style={{
        position: "fixed",
        right: 0,
        top: "50%",
        transform: "translateY(-50%)",
        zIndex: 200,
        background: hovered
          ? "linear-gradient(135deg, #2AA3B8 0%, #1787ac 100%)"
          : "linear-gradient(135deg, #1787ac 0%, #145f76 100%)",
        border: "none",
        borderRadius: "8px 0 0 8px",
        padding: "18px 10px",
        cursor: "pointer",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 8,
        boxShadow: "-2px 0 16px rgba(23,135,172,0.25)",
        transition: "background 0.2s, box-shadow 0.2s",
        fontFamily: "inherit",
      }}
    >
      {/* Avatar icon */}
      <div
        style={{
          width: 36,
          height: 36,
          borderRadius: "50%",
          background: "rgba(255,255,255,0.2)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="8" r="4" fill="white" />
          <path d="M4 20c0-4.4 3.6-8 8-8s8 3.6 8 8" stroke="white" strokeWidth="2" strokeLinecap="round" />
        </svg>
      </div>
      {/* Rotated label */}
      <span
        style={{
          fontSize: 9,
          fontWeight: 800,
          letterSpacing: "0.14em",
          textTransform: "uppercase",
          color: "rgba(255,255,255,0.9)",
          writingMode: "vertical-rl",
          transform: "rotate(180deg)",
          lineHeight: 1,
        }}
      >
        AI Influencer
      </span>
      {/* Pulse dot */}
      <div
        style={{
          width: 8,
          height: 8,
          borderRadius: "50%",
          background: "#c3d99a",
          boxShadow: "0 0 0 2px rgba(195,217,154,0.3)",
        }}
      />
    </button>
  );
}

// ─── Root ─────────────────────────────────────────────────────────────────────

export default function App() {
  const [view, setView] = useState<View>({ kind: "home" });

  const [prevView, setPrevView] = useState<View>({ kind: "home" });

  // Live data: fetched once from the Flask backend on mount, then held in
  // the `entries` module store (see data.ts / api.ts) that every page reads
  // from directly - no changes needed to Home/Section/Story page internals.
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState<LiveStats>({
    totalUpdates: 0, sectionCount: 8, importedCount: 0, lastGenerated: "",
  });
  const [summary, setSummary] = useState<LiveSummary | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const result = await fetchLiveEntries();
      const liveSummary = await fetchLiveSummary();
      if (cancelled) return;
      setStats(result.stats);
      setSummary(liveSummary);
      setLoading(false);
    })();
    return () => { cancelled = true; };
  }, []);

  const goHome = () => setView({ kind: "home" });
  const goSection = (section: SectionName) => setView({ kind: "section", section });
  const goStory = (entry: Entry) => setView({ kind: "story", entry });
  const goInfluencer = () => {
    setPrevView(view);
    setView({ kind: "influencer" });
  };
  const goBack = () => {
    if (view.kind === "influencer") {
      setView(prevView);
    } else if (view.kind === "story") {
      setView({ kind: "section", section: view.entry.section });
    } else {
      goHome();
    }
  };

  if (loading) {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "'Poppins', sans-serif", color: "#8c939c", fontSize: 13 }}>
        Loading digest…
      </div>
    );
  }

  return (
    <div style={{ minHeight: "100vh", fontFamily: "'Poppins', sans-serif" }}>
      {view.kind === "home" && (
        <HomePage onSection={goSection} onStory={goStory} stats={stats} summary={summary} />
      )}
      {view.kind === "section" && (
        <SectionPage section={view.section} onBack={goHome} onStory={goStory} />
      )}
      {view.kind === "story" && (
        <StoryPage entry={view.entry} onBack={goBack} onStory={goStory} />
      )}
      {view.kind === "influencer" && (
        <InfluencerPage onBack={goBack} />
      )}

      {/* Floating side button — hidden on the influencer page itself */}
      {view.kind !== "influencer" && (
        <InfluencerButton onClick={goInfluencer} />
      )}

      {/* "Ask about the news" chat — floating bottom-right */}
      {view.kind !== "influencer" && <AskAgent />}
    </div>
  );
}
