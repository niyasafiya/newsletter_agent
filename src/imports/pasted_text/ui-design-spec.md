Technomak Executive Digest — UI Design Specification
For recreating in Figma
1. What this is

An internal company newsletter/digest web app for Technomak. It tracks company updates across 8 categories and presents them as a browsable, searchable digest with three page levels:

Home / Cover page — all sections previewed on one scrolling page
Section archive page — every update in one section, opened by clicking a section name
Single story page — one update's full text, opened via "Read more"
2. Colors (exact hex values)
Role	Hex	Notes
Primary teal	
#1787ac	Main brand color — masthead text, links, primary buttons, tag accents
Secondary teal	
#2AA3B8	Used in gradients paired with primary teal
Dark teal (gradient end)	
#145f76 / 
#1a7686	Bottom of teal gradients on panels/tiles
Ink (headings/body)	
#1c1f24	Near-black, used for headings and rules
Body text	
#4a5058	Paragraph text
Dim/muted text	
#8c939c	Captions, labels, placeholder text
Border/rule	
#dfe3e8	Hairline dividers, input borders
Olive/light green accent	
#c3d99a (bg) / 
#4a5a1f (text)	Callout boxes, quote panels
Background	
#ffffff	Page background throughout
Risk tag	
#c0453a (red)	
Active/Deployed/Opportunity tag	
#2e8b7a (teal-green)	
Pending tag	
#8c939c (gray)	

Section accent colors (used as the colored rule/bar next to each section heading):

Project Portfolio → blue 
#2F5FE0
Competitor Intelligence → red/orange 
#c0453a
Marketing & Sales → pink/magenta 
#D6336C
EA / Systems Integration → purple 
#7C4DFF
Team & Leadership → teal 
#2e8b7a
Ops & Feedback → blue 
#0EA5C4
What's New → green 
#65A30D
News & Blogs → red 
#E1553F
3. Typography

Font family: Poppins (Google Font) — weights 400, 500, 600, 700, 800, 900 loaded.

Element	Size	Weight	Notes
Masthead ("NEWSLETTER")	44–98px (responsive/clamp)	900	Uppercase, letter-spacing -0.03em, color = primary teal
"EXECUTIVE DIGEST" subtitle	12–17px	600	Uppercase, letter-spacing +0.34em (very wide tracking)
Section heading	20–29px	800	Letter-spacing -0.02em
Lead panel heading ("Top news")	30px	800	White text on teal background
Lead panel title	19px	700	White text
Card title	19px (25px if "wide" card)	800	Letter-spacing -0.015em
Body/paragraph text	12–14px	400	
Kicker/label (tags, "Read more", section counts)	9–11px	700–800	Uppercase, letter-spacing +0.08 to +0.16em
Stat tile number	30px	900	White, on gradient background
Stat tile label	10px	600	Uppercase-ish, muted white
4. Page 1 — Home / Cover
4.1 Header bar (sticky, optional)
Left: "technomak" + ".digest" (in accent color) wordmark
Center: horizontal nav — small colored dot + section name, for all 8 sections
Right: black pill button labeled "Admin"
4.2 Hero block
Edition line row: left = "Quarter 3 Edition · September 2026" (small, gray); right = "TECHNOMAK" chip (teal background, white bold uppercase text, small padding)
Masthead: "NEWSLETTER" — huge, uppercase, teal, weight 900
Subtitle row: "EXECUTIVE DIGEST" (wide letter-spacing) + thin horizontal rule fading to the right
Search bar: bordered input, search icon inside on the left, placeholder "Search all updates — projects, competitors, risks…"
Stat tile row: 4 tiles side by side, equal width, each with a teal→dark-teal diagonal gradient background (alternating two gradient variants), white large number on top, white/light small label below. Tiles: "Total updates", "Tracked sections", "Imported via upload / URL", "Last generated"
4.3 Optional: AI executive summary

A soft blue-gradient rounded panel with a small icon + "Executive summary" heading, a few bullet lines of text, and a small "Generated [date]" caption top-right.

4.4 Optional: Key metrics

A small grid of chart cards (bar charts comparing figures, a donut chart of tag distribution) — secondary priority for the Figma mockup, can be a simple placeholder block.

4.5 Repeating section block (× 8, one per section)

Each section on the home page follows this exact pattern:

a. Section header row:

Section name (large, bold, clickable — this is a link to the section's archive page)
A colored horizontal rule (3px thick) filling remaining width, in that section's accent color
Small gray text on the right: "N updates"

b. Lead / "Top news" panel — a two-column block, no gap between columns:

Left column: solid or gradient teal background, padded ~28px. Contains: "Top news" (white, 30px, bold) → the entry's title as a large white pull-quote-style line (19px bold) → a paragraph of body text (smaller, lighter teal-white) → a small caption line: "publisher · date · Read the full update →"
Right column: bordered box (light gray border, no left border so it joins seamlessly with the teal column). Contains: entry's image on top (or a placeholder icon if no image, ~210px tall) → below the image: a small colored tag label → a paragraph of continuation text or a generic "Open the full update for complete detail…" line

c. Card grid below the lead panel:

3 columns (responsive: 1 column mobile, 2 tablet, 3 desktop)
First card in the grid can optionally span 2 columns ("wide" variant) with a larger image and bigger title
Each card: white background, 2px solid dark top border (no rounded corners, no shadow — flat editorial style), optional image on top (~150px, or ~190px for wide cards), small colored uppercase tag + thin rule + date on one line, bold title below (19px, or 25px if wide), a short body excerpt, then a footer row with the publisher name (left) and "Read more →" (right, colored, small caps)

d. "Read all" footer:

A row with: colored "Read all [Section Name] updates →" text (links to that section's archive page) + a thin rule filling the remaining space + gray "+N more" text on the right, all sitting above a 2px dark top border

This whole block (a–d) repeats 8 times, once per section, in this order: Project Portfolio, Competitor Intelligence, Marketing & Sales, EA / Systems Integration, Team & Leadership, Ops & Feedback, What's New, News & Blogs.

4.6 Footer

Dark/black full-width bar containing: confidentiality notice text (left) and an "Admin console →" link (right).

5. Page 2 — Section Archive

Opened when a section name or "Read all" link is clicked.

Back link: "← Back to digest" — bold, small caps, bottom border, top-left of page
Section heading: the section name, large (26–38px), bold, with a thin top rule above it
Count line: small gray text — "N updates — full archive"
Card grid: every entry in that section, using the same card component as the home page grid (3 columns, same styling, no lead panel here — just the flat grid)
6. Page 3 — Single Story

Opened via any "Read more" link.

Back link: "← Back to digest"
Eyebrow: "[Section Name] · [Tag]" in small colored caps
Title: large bold heading (24–40px)
Byline row: publisher name · date · source type, small gray text, thin rule beneath
Body: full text, comfortable reading width (~660px max), larger body font (16–17px) for readability
Related section: below a rule, "More in [Section]" label + a short list of 2–3 other entry titles from the same section, each linking to its own story page
7. Card component reference (used throughout)

A single reusable "article card":

┌─────────────────────────────┐
│ [image, optional]           │  ← 150px tall (190px if "wide")
├─────────────────────────────┤
│ TAG ─────────────── DATE    │  ← small uppercase tag (colored) + thin rule + date
│ Card Title Goes Here        │  ← bold, 19px (25px if wide)
│ Short excerpt text of the   │
│ update body, one to two     │
│ lines truncated with an     │
│ ellipsis…                   │
├─────────────────────────────┤
│ Publisher Name   Read more →│  ← footer row, publisher left, link right
└─────────────────────────────┘
No rounded corners, no drop shadow — flat, editorial look
2px solid dark top border is the card's only strong visual boundary
On hover: subtle background tint change and the "Read more" text shifts slightly right
8. Content model (what data each entry/card needs)

Each entry (card) has:

Section (one of the 8 listed above)
Title (headline)
Body (full paragraph text)
Tag (status label — one of: Active, Deployed, Testing, Development, Risk, Opportunity, Industry, Pending, Leadership, New)
Date
Publisher (person or team name)
Image (optional photo)
9. Overall visual tone
Editorial/magazine, not SaaS dashboard — flat colors, sharp corners, hairline rules and heavy top-borders instead of rounded cards and drop shadows
Teal + white + near-black is the entire palette, with olive/light-green used sparingly as a single accent for callouts
Generous whitespace between sections, tight spacing within a card
Typography does the work — big weight contrasts (900 for display, 400 for body, 700–800 for emphasis) rather than color or decoration carrying hierar