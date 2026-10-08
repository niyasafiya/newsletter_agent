export type Tag =
  | "Active"
  | "Deployed"
  | "Testing"
  | "Development"
  | "Risk"
  | "Opportunity"
  | "Industry"
  | "Pending"
  | "Leadership"
  | "Headcount"
  | "Draft"
  | "New";

export type SectionName =
  | "Project Portfolio"
  | "Competitor Intelligence"
  | "Marketing & Sales"
  | "EA / Systems Integration"
  | "Team & Leadership"
  | "Ops & Feedback"
  | "What's New"
  | "News & Blogs";

export interface Entry {
  id: string;
  section: SectionName;
  title: string;
  body: string;
  tag: Tag;
  date: string;
  publisher: string;
  image?: string;
}

export const sectionAccents: Record<SectionName, string> = {
  "Project Portfolio": "#2F5FE0",
  "Competitor Intelligence": "#c0453a",
  "Marketing & Sales": "#D6336C",
  "EA / Systems Integration": "#7C4DFF",
  "Team & Leadership": "#2e8b7a",
  "Ops & Feedback": "#0EA5C4",
  "What's New": "#65A30D",
  "News & Blogs": "#E1553F",
};

export const tagColors: Record<Tag, { bg: string; text: string }> = {
  Active: { bg: "#d1fae5", text: "#2e8b7a" },
  Deployed: { bg: "#d1fae5", text: "#2e8b7a" },
  Opportunity: { bg: "#d1fae5", text: "#2e8b7a" },
  Testing: { bg: "#e0f2fe", text: "#1787ac" },
  Development: { bg: "#ede9fe", text: "#7C4DFF" },
  Risk: { bg: "#fee2e2", text: "#c0453a" },
  Industry: { bg: "#fef3c7", text: "#92400e" },
  Pending: { bg: "#f3f4f6", text: "#8c939c" },
  Leadership: { bg: "#f0fdf4", text: "#2e8b7a" },
  Headcount: { bg: "#e0f2fe", text: "#1787ac" },
  Draft: { bg: "#f3f4f6", text: "#8c939c" },
  New: { bg: "#f0fdf4", text: "#65A30D" },
};

// Fallback for any tag value that isn't one of the known ones above - e.g.
// something the AI draft tool invents, or a value typed directly through
// the API. Prevents a crash; just renders as a plain neutral pill instead.
const DEFAULT_TAG_COLOR = { bg: "#f3f4f6", text: "#4a5058" };

export function tagColor(tag: string): { bg: string; text: string } {
  return (tagColors as Record<string, { bg: string; text: string }>)[tag] || DEFAULT_TAG_COLOR;
}

export const sections: SectionName[] = [
  "Project Portfolio",
  "Competitor Intelligence",
  "Marketing & Sales",
  "EA / Systems Integration",
  "Team & Leadership",
  "Ops & Feedback",
  "What's New",
  "News & Blogs",
];

// `entries` starts empty and is populated at runtime from the live Flask
// backend (see fetchLiveEntries in api.ts). It's a `let`, not `const`, so
// every component that reads it (Home/Section/Story pages) sees the live
// data on their next render after setEntries() runs - no prop drilling
// needed, no component code changes required.
export let entries: Entry[] = [];

export function setEntries(next: Entry[]): void {
  entries = next;
}
