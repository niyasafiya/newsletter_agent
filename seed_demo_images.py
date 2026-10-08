"""Generate placeholder images for a demo and attach them to entries.

These are abstract geometric graphics drawn in code - not photographs. They
exist so the magazine layout has something in every image slot while you
gather real Technomak photos. Replace them by uploading a real picture
through the publish form.

Run once, with the backend stopped:

    pip install pillow --break-system-packages
    python seed_demo_images.py

Options:
    python seed_demo_images.py --clear    remove demo images from all entries
"""

import os
import random
import sqlite3
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "technomak.db")
MEDIA = os.path.join(HERE, "media")
W, H = 1200, 720
PREFIX = "demo_"

# Blue-magazine palette, matching the app theme.
SKY = (223, 233, 239)
PALETTE = [(27, 143, 199), (42, 163, 184), (111, 163, 192), (93, 147, 178),
           (143, 176, 196), (77, 135, 168), (169, 196, 211)]
LIGHT = (232, 242, 247)


def _bg(draw, horizon):
    draw.rectangle([0, 0, W, H], fill=SKY)
    draw.rectangle([0, horizon, W, H], fill=(169, 196, 211))


def skyline(draw, rnd):
    """City / plant skyline."""
    _bg(draw, int(H * 0.72))
    x = 40
    while x < W - 60:
        w = rnd.randint(70, 150)
        h = rnd.randint(150, 420)
        top = int(H * 0.72) - h
        draw.rectangle([x, top, x + w, int(H * 0.72)], fill=rnd.choice(PALETTE))
        for wy in range(top + 24, int(H * 0.72) - 30, 46):
            for wx in range(x + 16, x + w - 20, 38):
                if rnd.random() > 0.35:
                    draw.rectangle([wx, wy, wx + 16, wy + 18], fill=LIGHT)
        x += w + rnd.randint(14, 34)
    draw.ellipse([W - 190, 50, W - 90, 150], fill=LIGHT)


def pipes(draw, rnd):
    """Industrial pipework / process plant."""
    _bg(draw, int(H * 0.78))
    for i in range(5):
        y = 120 + i * 105
        draw.rectangle([0, y, W, y + 44], fill=rnd.choice(PALETTE))
        for x in range(90, W, 210):
            draw.rectangle([x, y - 10, x + 26, y + 54], fill=(240, 246, 250))
    for x in range(140, W, 260):
        draw.rectangle([x, 90, x + 40, int(H * 0.78)], fill=(77, 135, 168))


def barchart(draw, rnd):
    """Data / metrics graphic."""
    draw.rectangle([0, 0, W, H], fill=SKY)
    base = int(H * 0.82)
    draw.line([70, base, W - 70, base], fill=(140, 160, 175), width=4)
    x = 120
    bars = 7
    for i in range(bars):
        h = rnd.randint(110, 460)
        colour = (27, 143, 199) if i == bars - 1 else rnd.choice(PALETTE[2:])
        draw.rectangle([x, base - h, x + 96, base], fill=colour)
        x += 140


def team(draw, rnd):
    """Abstract group of people."""
    _bg(draw, int(H * 0.74))
    positions = [(210, 330), (400, 300), (600, 340), (800, 310), (990, 345)]
    for cx, cy in positions:
        c = rnd.choice(PALETTE)
        r = rnd.randint(52, 70)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c)
        draw.rectangle([cx - r - 10, cy + r - 6, cx + r + 10, int(H * 0.86)], fill=c)


def gate(draw, rnd):
    """Gate / camera / access control."""
    _bg(draw, int(H * 0.76))
    draw.rectangle([120, 200, 190, int(H * 0.76)], fill=(77, 135, 168))
    draw.rectangle([W - 190, 200, W - 120, int(H * 0.76)], fill=(77, 135, 168))
    draw.rectangle([120, 200, W - 120, 262], fill=(27, 143, 199))
    draw.rectangle([300, 430, 900, 520], fill=(143, 176, 196))
    for x in range(320, 880, 70):
        draw.rectangle([x, 448, x + 40, 502], fill=LIGHT)
    draw.ellipse([560, 290, 640, 370], fill=(42, 163, 184))
    draw.ellipse([583, 313, 617, 347], fill=LIGHT)


def offshore(draw, rnd):
    """Offshore platform / marine."""
    draw.rectangle([0, 0, W, H], fill=SKY)
    draw.rectangle([0, int(H * 0.66), W, H], fill=(111, 163, 192))
    for i in range(6):
        y = int(H * 0.70) + i * 34
        draw.line([0, y, W, y], fill=(143, 176, 196), width=6)
    draw.rectangle([330, 250, 870, 340], fill=(77, 135, 168))
    for x in (380, 560, 740, 820):
        draw.rectangle([x, 340, x + 34, int(H * 0.70)], fill=(93, 147, 178))
    draw.rectangle([430, 150, 520, 250], fill=(27, 143, 199))
    draw.polygon([(640, 120), (700, 250), (580, 250)], fill=(42, 163, 184))


def documents(draw, rnd):
    """Documents / signatures / paperwork."""
    draw.rectangle([0, 0, W, H], fill=SKY)
    for i, (ox, oy) in enumerate([(180, 120), (330, 180), (480, 240)]):
        draw.rectangle([ox, oy, ox + 420, oy + 400], fill=(255, 255, 255))
        draw.rectangle([ox, oy, ox + 420, oy + 54], fill=PALETTE[i % len(PALETTE)])
        for ly in range(oy + 92, oy + 370, 42):
            draw.rectangle([ox + 34, ly, ox + 330, ly + 14], fill=(214, 226, 234))
    draw.line([700, 520, 800, 470, 860, 540, 960, 460], fill=(27, 143, 199), width=10)


def network(draw, rnd):
    """Systems / integration / data flow."""
    draw.rectangle([0, 0, W, H], fill=SKY)
    nodes = [(rnd.randint(140, W - 140), rnd.randint(130, H - 130)) for _ in range(9)]
    for i, a in enumerate(nodes):
        for b in nodes[i + 1:]:
            if rnd.random() > 0.62:
                draw.line([a, b], fill=(169, 196, 211), width=4)
    for i, (cx, cy) in enumerate(nodes):
        r = 34 if i % 3 else 52
        draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                     fill=(27, 143, 199) if i % 3 == 0 else rnd.choice(PALETTE[2:]))


DRAWERS = {
    "projects": [skyline, offshore, gate, pipes],
    "competitors": [barchart, skyline, network],
    "marketing": [barchart, documents, team],
    "ea": [network, pipes, documents],
    "team": [team, documents],
    "ops": [gate, pipes, team],
    "releases": [documents, network],
    "news": [skyline, barchart, offshore],
}


def make_images(variants_per_drawer=4):
    """Generates several distinct images per drawer function (different random
    seeds), so a section with many entries doesn't keep repeating the same
    few pictures."""
    os.makedirs(MEDIA, exist_ok=True)
    made = {}
    for section, drawers in DRAWERS.items():
        names = []
        for i, fn in enumerate(drawers):
            for v in range(variants_per_drawer):
                rnd = random.Random(f"{section}{i}{v}")
                img = Image.new("RGB", (W, H), SKY)
                fn(ImageDraw.Draw(img), rnd)
                name = f"{PREFIX}{section}_{i}_{v}.png"
                img.save(os.path.join(MEDIA, name), "PNG", optimize=True)
                names.append(name)
        made[section] = names
    return made


def attach(made, every=1):
    """Attach an image to every Nth entry in each section, cycling through
    every generated variant before any image repeats within that section."""
    if not os.path.exists(DB):
        print("No database found. Start the app once to create it, then rerun.")
        return 0
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(entries)")]
    if "image" not in cols:
        conn.execute("ALTER TABLE entries ADD COLUMN image TEXT")
    updated = 0
    for section, names in made.items():
        shuffled = names[:]
        random.Random(section).shuffle(shuffled)
        rows = conn.execute(
            "SELECT id FROM entries WHERE section = ? ORDER BY id DESC",
            (section,),
        ).fetchall()
        pos = 0
        for i, row in enumerate(rows):
            if i % every:
                continue
            conn.execute("UPDATE entries SET image = ? WHERE id = ?",
                         (shuffled[pos % len(shuffled)], row["id"]))
            pos += 1
            updated += 1
    conn.commit()
    conn.close()
    return updated


def clear():
    if not os.path.exists(DB):
        return 0
    conn = sqlite3.connect(DB)
    cur = conn.execute(
        "UPDATE entries SET image = NULL WHERE image LIKE ?", (PREFIX + "%",))
    conn.commit()
    n = cur.rowcount
    conn.close()
    for f in os.listdir(MEDIA) if os.path.isdir(MEDIA) else []:
        if f.startswith(PREFIX):
            os.remove(os.path.join(MEDIA, f))
    return n


if __name__ == "__main__":
    if "--clear" in sys.argv:
        print(f"Removed demo images from {clear()} entries.")
    else:
        made = make_images()
        total = sum(len(v) for v in made.values())
        n = attach(made)
        print(f"Created {total} placeholder images in ./media")
        print(f"Attached them to {n} entries.")
        print("Restart the backend and reload the digest.")
        print("Remove them any time with: python seed_demo_images.py --clear")
