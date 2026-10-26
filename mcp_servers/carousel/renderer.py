"""Prism carousel renderer — AI Dev Digest format v3 ("Front Page" system).

PORTED from the production LinkedIn pipeline's donor renderer:
  ~/workspace/goals/linkedin-profile-overhaul-for-lead-ai-architect-director-roles/
      tools/carousel_digest_themes.py
(segments extracted and adapted 2026-10-24; credit: that file's Round 3-5
layout engines by Sunny for Venugopal's AI Dev Digest.)

v3 STRUCTURE — fixed 8 pages, 1080x1350, every edition:
  1 masthead cover: lead story headline + deck + "ALSO IN TODAY'S DIGEST"
    contents (the other 4 stories)
  2-6 five story slides (heading, why-it-matters bullets, verdict strip)
  7 "Today in one screen" recap: 5 headlines + verdicts + quotable take
  8 person-led CTA (persona avatar + name + position + follow lines)

Skins: poster is the standing Digest default for every edition (Venugopal,
locked 2026-10-16–20); frontpage is an alternate light skin on request and
terminal / neon-grid / aurora are special-occasion only. The legacy edition
rotation over [frontpage, terminal, neon-grid, poster, aurora],
skin = ROTATION[(edition - 1) % 5], applies only when a playbook explicitly
opts in (carousel.skin_mode: rotation). "sunset" is the Travel family's skin:
the frontpage layout in warm sunset colours (same structure, swapped theme).
statdeck is REJECTED (Venugopal, 2026-10-14) — not ported, never used.

B-roll rule (v3): hybrid topical photos ONLY in the neon-grid and aurora
skins, only when a slide spec carries a validated local "broll" image;
renderer applies the donor's blurred/darkened treatment and falls back to
the flat skin background on ANY failure — an image never blocks a render.

Shared module: imported directly by the agent's makers AND exposed over MCP
by server.py in this folder.
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1080, 1350
FD = "/usr/share/fonts/truetype/dejavu"
MAX_BULLET = 125  # standing carousel QA rule: longer bullets lose their tail

# Bundled assets (2026-10-25 fix): the deploy image has NO system fonts and
# no workspace, so fonts and the persona photo ship inside the repo and are
# resolved relative to this file. System/workspace paths remain fallbacks
# for local dev only.
_HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(_HERE, "assets")
FONT_DIR = os.path.join(ASSETS_DIR, "fonts")
BUNDLED_PHOTO = os.path.join(ASSETS_DIR, "venu-tati-avatar.jpg")
HEADLINE_FLOOR = 36  # QA gate: cover headline may never render below this

# ---- render QA gate state (reset per render in render_carousel) ----
_QA = {"fonts_ok": True, "avatar": None, "cover_headline_size": None}
_BOXES = []  # (page, x0, y0, x1, y1, label) for every tracked text block
_PAGE = [0]


def _reset_qa():
    _QA.update({"fonts_ok": True, "avatar": None, "cover_headline_size": None})
    _BOXES.clear()


def _track(d, x, y, text, f, label, anchor=None):
    try:
        b = d.textbbox((x, y), text, font=f, anchor=anchor)
    except Exception:
        return
    _BOXES.append((_PAGE[0], b[0], b[1], b[2], b[3], label))


def _page_overlaps(page):
    boxes = [b for b in _BOXES if b[0] == page]
    n = 0
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            if (min(a[3], b[3]) - max(a[1], b[1]) > 4
                    and min(a[4], b[4]) - max(a[2], b[2]) > 4):
                n += 1
    return n


# Persona is set per-render from the spec (defaults = the Digest persona).
_PERSONA_NAME = "Venu Tati"
_PERSONA_PHOTO = ""


def _photo_candidates():
    paths = []
    if _PERSONA_PHOTO:
        paths.append(_PERSONA_PHOTO)
    if os.environ.get("PRISM_PERSONA_PHOTO"):
        paths.append(os.environ["PRISM_PERSONA_PHOTO"])
    paths.append(BUNDLED_PHOTO)
    home = os.path.expanduser("~")
    paths += [f"{home}/workspace/profile-images/venu-tati-avatar.jpg",
              f"{home}/workspace/profile-images/user-profile-reference.jpg"]
    return paths


def circle_photo(d):
    """Circular persona avatar: real photo when available, else a monogram
    disc in the persona's initials (never blocks a render)."""
    for p in _photo_candidates():
        try:
            if p and os.path.exists(p):
                im = Image.open(p).convert("RGB")
                w, h = im.size
                side = min(w, h)
                face = im.crop(((w - side) // 2, (h - side) // 2,
                                (w - side) // 2 + side, (h - side) // 2 + side))
                inner = int(d * 0.96)
                face = face.resize((inner, inner), Image.LANCZOS)
                canvas = Image.new("RGBA", (d, d), (0, 0, 0, 0))
                canvas.paste(face, ((d - inner) // 2, (d - inner) // 2))
                mask = Image.new("L", (d, d), 0)
                ImageDraw.Draw(mask).ellipse((0, 0, d, d), fill=255)
                out = Image.new("RGBA", (d, d), (0, 0, 0, 0))
                out.paste(canvas, (0, 0), mask)
                _QA["avatar"] = "photo"
                return out
        except Exception:
            continue
    # Monogram fallback
    _QA["avatar"] = "monogram"
    out = Image.new("RGBA", (d, d), (0, 0, 0, 0))
    dd = ImageDraw.Draw(out)
    dd.ellipse((2, 2, d - 2, d - 2), fill=(124, 108, 240, 255))
    initials = "".join(w[0] for w in _PERSONA_NAME.split()[:2]).upper() or "VT"
    try:
        f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", int(d * 0.38))
    except Exception:
        f = ImageFont.load_default()
    dd.text((d // 2, d // 2), initials, font=f, fill=(255, 255, 255), anchor="mm")
    return out

def _font_file(name):
    for base in (FONT_DIR, FD):
        p = os.path.join(base, f"{name}.ttf")
        if os.path.exists(p):
            return p
    return None


def font(name, size):
    p = _font_file(name)
    if p:
        try:
            f = ImageFont.truetype(p, size)
            if getattr(f, "size", None) == size:
                return f
        except Exception:
            pass
    # Real TTF unavailable (or wrong size): the QA gate must know — a silent
    # load_default() fallback is what shipped the broken Oct 25 PDF.
    _QA["fonts_ok"] = False
    return ImageFont.load_default()

def fit(draw, text, name, max_w, start, min_s=24):
    s = start
    while s > min_s:
        f = font(name, s)
        if max(draw.textbbox((0,0), ln, font=f)[2] for ln in text.split("\n")) <= max_w:
            return f
        s -= 4
    return font(name, min_s)

def ellipsize(d, text, f, max_w):
    """Truncate at a word boundary with an ellipsis so text fits max_w."""
    if d.textbbox((0, 0), text, font=f)[2] <= max_w:
        return text
    out = ""
    for w_ in text.split():
        t = (out + " " + w_).strip()
        if d.textbbox((0, 0), t + "…", font=f)[2] <= max_w:
            out = t
        else:
            break
    return (out + "…") if out else "…"

def fit_draw(d, x, y, text, name, max_w, start, min_s, fill, anchor=None, label="text"):
    """Fit-to-width single-line draw: shrink to min_s, then ellipsize —
    never overflow the box. Registers the drawn box with the QA gate."""
    f = fit(d, text, name, max_w, start, min_s=min_s)
    if d.textbbox((0, 0), text, font=f)[2] > max_w:
        text = ellipsize(d, text, f, max_w)
    d.text((x, y), text, font=f, fill=fill, anchor=anchor)
    if anchor is None:
        _track(d, x, y, text, f, label)
    return f

def wrap(draw, text, f, max_w):
    words, lines, cur = text.split(), [], ""
    for w_ in words:
        t = (cur + " " + w_).strip()
        if draw.textbbox((0,0), t, font=f)[2] <= max_w:
            cur = t
        else:
            lines.append(cur); cur = w_
    if cur: lines.append(cur)
    return lines

def bg_for(t):
    if t.get("flat"):
        return Image.new("RGB", (W, H), t["bg"][1])
    top, mid, bot = t["bg"]
    img = Image.new("RGB", (W, H)); d = ImageDraw.Draw(img)
    for y in range(H):
        tt = y/(H-1)
        if tt < 0.5:
            u = tt*2; c = tuple(int(top[i]+(mid[i]-top[i])*u) for i in range(3))
        else:
            u = (tt-0.5)*2; c = tuple(int(mid[i]+(bot[i]-mid[i])*u) for i in range(3))
        d.line((0, y, W, y), fill=c)
    if t.get("grid"):
        gd = ImageDraw.Draw(img)
        for gx in range(0, W, 72):
            gd.line((gx, 0, gx, H), fill=(120, 200, 255, 22))
        for gy in range(0, H, 72):
            gd.line((0, gy, W, gy), fill=(120, 200, 255, 22))
    ov = Image.new("RGBA", (W, H), (0,0,0,0))
    for (cx, cy, r, col) in t["glows"]:
        m = Image.new("L", (W, H), 0)
        ImageDraw.Draw(m).ellipse((cx-r, cy-r, cx+r, cy+r), fill=255)
        m = m.filter(ImageFilter.GaussianBlur(120))
        ov = Image.alpha_composite(ov, Image.composite(Image.new("RGBA",(W,H),col), Image.new("RGBA",(W,H),(0,0,0,0)), m))
    return Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")

def _lum(im):
    """Mean perceived luminance 0-255 (pure PIL — donor used numpy)."""
    small = im.convert("RGB").resize((24, 24))
    px = list(small.getdata())
    return sum(0.299 * r + 0.587 * g + 0.114 * b for r, g, b in px) / len(px)

def broll_bg(path, t, blur=20, base_alpha=90, max_alpha=225, lum_cap=80):
    """Blurred topical background with ADAPTIVE darkening.

    Light source images (e.g. light-UI screenshots) get pushed much darker so
    the slide keeps the theme's deep-navy read; dark photos keep the standard
    35% treatment. Returns None when even max darkening leaves the background
    too light — caller falls back to the flat theme background.
    """
    im = Image.open(path).convert("RGB")
    sw, sh = im.size
    scale = max(W/sw, H/sh)
    im = im.resize((int(sw*scale)+1, int(sh*scale)+1), Image.LANCZOS)
    x = (im.width - W)//2; y = (im.height - H)//2
    im = im.crop((x, y, x+W, y+H))
    im = im.filter(ImageFilter.GaussianBlur(blur))
    lum = _lum(im)
    alpha = min(max_alpha, max(base_alpha, int((lum - 30) * 1.15)))
    dark = Image.new("RGBA", (W, H), (8, 10, 20, alpha))
    out = Image.alpha_composite(im.convert("RGBA"), dark).convert("RGB")
    if _lum(out) > lum_cap:
        return None
    return out

THEMES = {
    "terminal": {  # dev console: near-black, phosphor green, mono everything, log layout
        "bg": [(7, 10, 7), (7, 10, 7), (7, 10, 7)],
        "glows": [],
        "text": (232, 255, 238), "sub": (158, 190, 165),
        "kicker": (74, 246, 128), "card": (74, 246, 128, 18), "ring": (74, 246, 128),
        "flat": True, "layout": "terminal",
        "dim": (96, 140, 105), "rule_c": (34, 58, 40), "chrome": (17, 22, 17),
    },
    "neon-grid": {  # violet-black, cyan->magenta gradient accents, blueprint grid, glass panels
        "bg": [(16, 7, 34), (22, 9, 48), (8, 4, 20)],
        "glows": [(905, 235, 400, (0, 229, 255, 42)), (165, 1120, 430, (255, 0, 190, 38)), (540, 690, 330, (130, 70, 255, 30))],
        "text": (255, 255, 255), "sub": (206, 198, 235),
        "kicker": (0, 229, 255), "card": (255, 255, 255, 22), "ring": (0, 229, 255),
        "layout": "neon", "accent2": (255, 0, 190), "panel_line": (140, 120, 255),
    },
    "poster": {  # Swiss/brutalist: off-white, black type, loud per-slot accent block, giant numerals
        "bg": [(246, 245, 240), (246, 245, 240), (246, 245, 240)],
        "glows": [],
        "text": (14, 14, 16), "sub": (70, 70, 74),
        "kicker": (255, 62, 0), "card": (255, 255, 255, 0), "ring": (14, 14, 16),
        "flat": True, "layout": "poster",
        "slot_accents": {"PRODUCT": (255, 62, 0), "FRAMEWORKS": (0, 64, 255), "REPO": (0, 158, 79), "RESEARCH": (138, 0, 255), "ECOSYSTEM": (232, 145, 0),
                         "DESTINATIONS": (255, 62, 0), "DEALS": (0, 64, 255), "ROUTES": (0, 158, 79), "GUIDES": (138, 0, 255), "NEWS": (232, 145, 0)},
    },
    "aurora": {  # gradient mesh + frosted rounded glass cards, calm premium
        "bg": [(19, 15, 56), (11, 27, 54), (6, 10, 30)],
        "glows": [(885, 255, 430, (45, 220, 200, 52)), (175, 1085, 470, (150, 90, 255, 48)), (545, 700, 360, (255, 90, 160, 28))],
        "text": (255, 255, 255), "sub": (214, 222, 240),
        "kicker": (150, 240, 214), "card": (255, 255, 255, 36), "ring": (150, 240, 214),
        "layout": "aurora",
    },
    "frontpage": {  # Archetype C: Rundown/Superhuman news front page — paper, ink, red accent
        "bg": [(250, 249, 245), (250, 249, 245), (250, 249, 245)],
        "glows": [],
        "text": (18, 18, 22), "sub": (92, 88, 82),
        "kicker": (178, 30, 30), "card": (255, 255, 255, 0), "ring": (18, 18, 22),
        "flat": True, "layout": "frontpage",
        "hair": (203, 198, 188),
    },
    "sunset": {  # Travel family: frontpage layout, warm sunset paper/ink/terracotta
        "bg": [(252, 244, 231), (252, 244, 231), (252, 244, 231)],
        "glows": [],
        "text": (34, 24, 18), "sub": (110, 88, 70),
        "kicker": (234, 88, 12), "card": (255, 255, 255, 0), "ring": (34, 24, 18),
        "flat": True, "layout": "frontpage",
        "hair": (226, 205, 182),
    },
}

ROTATION = ["frontpage", "terminal", "neon-grid", "poster", "aurora"]
BROLL_SKINS = {"neon-grid", "aurora"}


def skin_for_edition(edition: int) -> str:
    return ROTATION[(edition - 1) % len(ROTATION)]

def _rgba(t):
    return bg_for(t).convert("RGBA")

def _finish(img):
    return img.convert("RGB")

def _lockup2(base, t, idx, total, name_fill, ring, num_fill, name_font=None, num_font=None, num_xy=(80, H-118)):
    d = ImageDraw.Draw(base); s = 150
    x, y = W-80-s, H-80-s
    f = name_font or font("DejaVuSans-Bold", 30)
    tw = d.textbbox((0, 0), _PERSONA_NAME, font=f)[2]
    d.text((x-tw-24, y+s//2-20), _PERSONA_NAME, font=f, fill=name_fill)
    _track(d, x-tw-24, y+s//2-20, _PERSONA_NAME, f, "lockup-name")
    d.ellipse((x-6, y-6, x+s+6, y+s+6), outline=ring, width=5)
    ph = circle_photo(s); base.paste(ph, (x, y), ph)
    d = ImageDraw.Draw(base)
    d.text(num_xy, f"{idx:02d} / {total:02d}", font=num_font or font("DejaVuSans", 26), fill=num_fill)

def _heading(d, text, fname, size, max_w, fill, x, y, min_s=30, qa_key=None, label="heading"):
    """Uniform-size heading: wraps to 2 lines at full size; shrinks only if
    >2 lines — and at the size floor it truncates at a word boundary with an
    ellipsis instead of silently dropping the overflow (or the whole block)."""
    s, f = size, font(fname, size)
    lines = wrap(d, text, f, max_w)
    while len(lines) > 2 and s > min_s:
        s -= 4; f = font(fname, s); lines = wrap(d, text, f, max_w)
    if len(lines) > 2:
        words = text.split()
        while words and len(lines) > 2:
            words.pop()
            lines = wrap(d, " ".join(words) + "…", f, max_w)
    if qa_key:
        _QA[qa_key] = s
    for ln in lines[:2]:
        d.text((x, y), ln, font=f, fill=fill)
        _track(d, x, y, ln, f, label)
        y += int(s * 1.18)
    return y

def _lead_heading(spec):
    """Cover headline: the framed display headline/angle when the makers
    provided one, never the raw (over-long) source title."""
    lead = spec.get("lead") or {}
    return lead.get("display_headline") or lead.get("heading", "")

def _glass_r(base, x, y, w, h, fill, outline=None, radius=26, width=2):
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(ov).rounded_rectangle((x, y, x+w, y+h), radius=radius, fill=fill, outline=outline, width=width)
    base.alpha_composite(ov)

def _hgrad(w, h, c1, c2, vertical=False):
    g = Image.new("RGB", (w, h)); gd = ImageDraw.Draw(g)
    n = h if vertical else w
    for i in range(n):
        u = i / max(n-1, 1)
        c = tuple(int(c1[k] + (c2[k]-c1[k]) * u) for k in range(3))
        if vertical: gd.line((0, i, w, i), fill=c)
        else: gd.line((i, 0, i, h), fill=c)
    return g

def _blend(c, bgc, f):
    """f=0 -> bgc, f=1 -> c."""
    return tuple(int(c[i]*f + bgc[i]*(1-f)) for i in range(3))

MB, M, SB, S, SRFB, SRF = "DejaVuSansMono-Bold", "DejaVuSansMono", "DejaVuSans-Bold", "DejaVuSans", "DejaVuSerif-Bold", "DejaVuSerif"

# ---------------- TERMINAL ----------------

def _verdict_strip(img, t, sl):
    """One-line verdict strip on story slides (v3: headline + why-it-matters
    bullets + verdict). Added in the Prism port — the donor carried verdicts
    only in the recap; Prism renders them on the story slide too."""
    v = (sl or {}).get("verdict")
    if not v:
        return
    d = ImageDraw.Draw(img)
    # Inset past the poster's left color bar (110 wide) + margin; sit above
    # the persona lockup (photo top = H-230) so the strip can run full width
    # without ever colliding with the lockup name/photo.
    x0 = 190 if t.get("layout") == "poster" else 80
    y = 1078
    d.rectangle((x0, y + 4, x0 + 12, y + 40), fill=t["kicker"])
    lf = font(MB, 24)
    d.text((x0 + 28, y), "VERDICT", font=lf, fill=t["kicker"])
    _track(d, x0 + 28, y, "VERDICT", lf, "verdict-label")
    vw = d.textbbox((0, 0), "VERDICT", font=lf)[2]
    tx = x0 + 28 + vw + 18
    fit_draw(d, tx, y + 2, v, S, W - 80 - tx, 27, 19, t["text"], label="verdict")

def _term_chrome(base, t):
    d = ImageDraw.Draw(base)
    d.rectangle((0, 0, W, 66), fill=t["chrome"])
    for i, c in enumerate([(206, 84, 72), (214, 164, 62), (64, 186, 94)]):
        cx = 42 + i*38
        d.ellipse((cx-11, 22, cx+11, 44), fill=c)
    d.text((160, 20), "venu@digest: ~/ai-dev-digest", font=font(M, 24), fill=t["sub"])
    d.line((0, 66, W, 66), fill=t["rule_c"], width=2)

def _term_cover(t, spec, total):
    img = _rgba(t); _term_chrome(img, t); d = ImageDraw.Draw(img)
    d.text((80, 150), "$ cat ai_dev_digest.md", font=font(MB, 30), fill=t["dim"])
    d.text((80, 225), "# " + spec["kicker"], font=font(MB, 36), fill=t["kicker"])
    d.text((80, 300), spec["title"], font=fit(d, spec["title"], MB, W-160, 104), fill=t["text"])
    d.line((80, 480, W-80, 480), fill=t["rule_c"], width=2)
    d.text((80, 530), "> " + spec["cover_sub"], font=font(MB, 42), fill=t["text"])
    d.text((80, 600), "> For builders, by a builder.", font=font(M, 38), fill=t["sub"])
    idx_line = "index: " + " / ".join(s["tag"] for s in spec["slides"]) if spec.get("slides") else ""
    if idx_line:
        d.text((80, 720), idx_line, font=font(M, 25), fill=t["dim"])
    d.text((80, 930), "> swipe ->", font=font(MB, 36), fill=t["kicker"])
    _lockup2(img, t, 1, total, t["text"], t["ring"], t["dim"], name_font=font(MB, 28), num_font=font(M, 26))
    return _finish(img)

def _term_story(t, spec, sl, entry, idx, total):
    img = _rgba(t); _term_chrome(img, t); d = ImageDraw.Draw(img)
    d.text((80, 104), f"[18:00:{entry:02d}] :: DAILY DIGEST :: ENTRY {entry:02d}", font=font(M, 25), fill=t["dim"])
    tag = sl.get("tag", "")
    tf = font(MB, 30); tw = d.textbbox((0, 0), f"[ {tag} ]", font=tf)[2]
    d.rectangle((80, 148, 80+tw+28, 148+54), outline=t["kicker"], width=2)
    d.text((94, 158), f"[ {tag} ]", font=tf, fill=t["kicker"])
    d.text((80, 238), ">", font=font(MB, 56), fill=t["kicker"])
    _heading(d, sl["heading"], MB, 56, W-160-52, t["text"], 132, 238, min_s=38)
    y = 500
    bf = font(M, 33)
    for b in sl["bullets"]:
        d.line((80, y, W-80, y), fill=t["rule_c"], width=2)
        lines = wrap(d, b, bf, W-160-56)
        ty = y + 22
        d.text((80, ty), "+", font=font(MB, 33), fill=t["kicker"])
        for ln in lines:
            d.text((124, ty), ln, font=bf, fill=t["text"]); ty += 46
        y = ty + 26
    d.line((80, y, W-80, y), fill=t["rule_c"], width=2)
    _verdict_strip(img, t, sl)
    _lockup2(img, t, idx, total, t["text"], t["ring"], t["dim"], name_font=font(MB, 28), num_font=font(M, 26))
    return _finish(img)
def _neon_bg(t, spec):
    img = _rgba(t)
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0)); gd = ImageDraw.Draw(ov)
    for gx in range(0, W, 72):
        gd.line((gx, 0, gx, H), fill=(120, 80, 255, 30 if gx % 360 else 52))
    for gy in range(0, H, 72):
        gd.line((0, gy, W, gy), fill=(120, 80, 255, 30 if gy % 360 else 52))
    img.alpha_composite(ov)
    return img

def _neon_pill(base, t, tag):
    d = ImageDraw.Draw(base)
    f = font(MB, 26); tw = d.textbbox((0, 0), tag, font=f)[2]
    pw, ph = tw + 48, 52
    x1, y1 = W-80-pw, 92
    grad = _hgrad(pw, ph, t["kicker"], t["accent2"]).convert("RGBA")
    mask = Image.new("L", (pw, ph), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, pw, ph), radius=ph//2, fill=255)
    base.paste(grad, (x1, y1), mask)
    d = ImageDraw.Draw(base)
    d.text((x1+24, y1+10), tag, font=f, fill=(10, 4, 24))

def _neon_panel(base, t, x, y, w, h):
    _glass_r(base, x, y, w, h, t["card"], outline=tuple(list(t["panel_line"]) + [130]), radius=22, width=2)
    strip = _hgrad(8, h, t["kicker"], t["accent2"], vertical=True).convert("RGBA")
    mask = Image.new("L", (8, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, 8, h), radius=4, fill=255)
    base.paste(strip, (x, y), mask)

def _neon_cover(t, spec, total):
    img = _neon_bg(t, spec); d = ImageDraw.Draw(img)
    d.text((80, 100), spec["kicker"], font=font(MB, 32), fill=t["kicker"])
    bar = _hgrad(260, 10, t["kicker"], t["accent2"]).convert("RGBA"); img.paste(bar, (80, 150), bar)
    d = ImageDraw.Draw(img)
    d.text((80, 195), spec["title"], font=fit(d, spec["title"], SB, W-160, 128), fill=t["text"])
    _glass_r(img, 80, 610, W-160, 215, t["card"], outline=tuple(list(t["kicker"]) + [160]), radius=28, width=2)
    d = ImageDraw.Draw(img)
    d.text((112, 652), spec["cover_sub"], font=fit(d, spec["cover_sub"], S, W-224, 48), fill=t["text"])
    d.text((112, 738), "For builders, by a builder.", font=font(S, 40), fill=t["sub"])
    d.text((80, 930), "swipe  ->", font=font(SB, 38), fill=t["text"])
    _lockup2(img, t, 1, total, t["text"], t["ring"], t["kicker"], num_font=font(M, 26))
    return _finish(img)

def _neon_story(t, spec, sl, entry, idx, total):
    bbg = broll_bg(sl["broll"], t) if sl.get("broll") else None
    if bbg is not None:
        img = bbg.convert("RGBA")
        img.alpha_composite(Image.new("RGBA", (W, H), (6, 4, 20, 35)))
    else:
        img = _neon_bg(t, spec)
    d = ImageDraw.Draw(img)
    d.text((80, 100), spec["kicker"], font=font(MB, 28), fill=t["kicker"])
    _heading(d, sl["heading"], SB, 66, W-160, t["text"], 80, 170)
    bullets = sl["bullets"]; nb = len(bullets)
    top, bottom, gap = 360, 1046, 24
    ch = (bottom - top - (nb-1)*gap)//nb
    y = top
    for b in bullets:
        _neon_panel(img, t, 80, y, W-160, ch); d = ImageDraw.Draw(img)
        bf = font(SB, 40)
        lines = wrap(d, b, bf, W-280)
        ty = y + (ch - len(lines)*56)//2 + 6
        for ln in lines:
            d.text((128, ty), ln, font=bf, fill=t["text"]); ty += 56
        y += ch + gap
    if sl.get("tag"):
        _neon_pill(img, t, sl["tag"])
    _verdict_strip(img, t, sl)
    _lockup2(img, t, idx, total, t["text"], t["ring"], t["kicker"], num_font=font(M, 26))
    return _finish(img)

def _poster_accent(t, tag):
    return t["slot_accents"].get(tag, t["kicker"])

def _poster_cover(t, spec, total):
    img = _rgba(t); d = ImageDraw.Draw(img)
    acc = t["kicker"]
    import re as _re
    m = _re.search(r"#(\d+)", spec["kicker"])
    ed = f"{int(m.group(1)):02d}" if m else "01"
    ghost = _blend(acc, t["bg"][0], 0.16)
    d.text((W-430, 110), ed, font=font(SB, 290), fill=ghost)
    d.rectangle((80, 108, 100, 128), fill=acc)
    d.text((116, 100), spec["kicker"], font=font(MB, 28), fill=t["text"])
    d.text((74, 190), "AI Dev", font=font(SB, 196), fill=t["text"])
    d.text((74, 396), "Digest", font=font(SB, 196), fill=t["text"])
    d.rectangle((80, 640, 470, 668), fill=acc)
    d.text((80, 720), spec["cover_sub"], font=fit(d, spec["cover_sub"], SB, W-160, 50), fill=t["text"])
    d.text((80, 800), "For builders, by a builder.", font=font(S, 38), fill=t["sub"])
    d.text((80, 950), "SWIPE ", font=font(MB, 36), fill=t["text"])
    sw = d.textbbox((0, 0), "SWIPE ", font=font(MB, 36))[2]
    d.text((80+sw, 950), "->", font=font(MB, 36), fill=acc)
    _lockup2(img, t, 1, total, t["text"], t["ring"], t["text"], num_font=font(SB, 32), num_xy=(80, H-124))
    return _finish(img)

def _poster_story(t, spec, sl, entry, idx, total):
    img = _rgba(t); d = ImageDraw.Draw(img)
    acc = _poster_accent(t, sl.get("tag", ""))
    d.rectangle((0, 0, 110, H), fill=acc)
    ghost = _blend(acc, t["bg"][0], 0.12)
    d.text((W-430, 16), f"{entry:02d}", font=font(SB, 370), fill=ghost)
    d.text((W-80, 84), spec["kicker"], font=font(MB, 22), fill=t["sub"], anchor="ra")
    tag = sl.get("tag", "")
    tf = font(MB, 26); tw = d.textbbox((0, 0), tag, font=tf)[2]
    d.rectangle((190, 96, 190+tw+44, 96+58), fill=acc)
    d.text((212, 110), tag, font=tf, fill=(255, 255, 255))
    y = _heading(d, sl["heading"], SB, 64, W-190-70, t["text"], 190, 210)
    y += 56
    bf = font(SB, 38)
    # Measured two-pass layout: wrap every bullet first, then distribute any
    # slack evenly between blocks so the slide fills its region (heading ->
    # verdict strip) instead of sitting half-empty.
    blocks = [wrap(d, b, bf, W-190-70-52) for b in sl["bullets"]]
    block_h = [len(lines) * 53 + 56 for lines in blocks]
    extra = 1046 - y - sum(block_h)
    gap = min(extra // max(1, len(blocks) - 1), 110) if len(blocks) > 1 and extra > 0 else 0
    for i, lines in enumerate(blocks):
        d.rectangle((190, y+14, 206, y+30), fill=acc)
        for ln in lines:
            d.text((242, y), ln, font=bf, fill=t["text"])
            _track(d, 242, y, ln, bf, "bullet")
            y += 53
        y += 26
        d.line((190, y, W-70, y), fill=t["text"], width=2)
        y += 30 + (gap if i < len(blocks) - 1 else 0)
    _verdict_strip(img, t, sl)
    _lockup2(img, t, idx, total, t["text"], t["ring"], t["text"], num_font=font(SB, 32), num_xy=(190, H-124))
    return _finish(img)

def _aurora_pill(base, t, tag):
    d = ImageDraw.Draw(base)
    f = font(MB, 26); tw = d.textbbox((0, 0), tag, font=f)[2]
    pw, ph = tw + 48, 52
    x1, y1 = W-80-pw, 92
    _glass_r(base, x1, y1, pw, ph, (255, 255, 255, 44), outline=tuple(list(t["kicker"]) + [220]), radius=ph//2, width=2)
    d = ImageDraw.Draw(base)
    d.text((x1+24, y1+10), tag, font=f, fill=(255, 255, 255))

def _aurora_cover(t, spec, total):
    img = _rgba(t); d = ImageDraw.Draw(img)
    d.text((80, 100), spec["kicker"], font=font(MB, 32), fill=t["kicker"])
    d.text((80, 195), spec["title"], font=fit(d, spec["title"], SB, W-160, 128), fill=t["text"])
    _glass_r(img, 80, 610, W-160, 215, t["card"], outline=(255, 255, 255, 110), radius=30, width=2)
    d = ImageDraw.Draw(img)
    d.text((112, 652), spec["cover_sub"], font=fit(d, spec["cover_sub"], S, W-224, 48), fill=t["text"])
    d.text((112, 738), "For builders, by a builder.", font=font(S, 40), fill=t["sub"])
    d.text((80, 930), "swipe  ->", font=font(SB, 38), fill=t["text"])
    _lockup2(img, t, 1, total, t["text"], t["ring"], t["sub"], num_font=font(M, 26))
    return _finish(img)

def _aurora_story(t, spec, sl, entry, idx, total):
    bbg = broll_bg(sl["broll"], t) if sl.get("broll") else None
    if bbg is not None:
        img = bbg.convert("RGBA")
        img.alpha_composite(Image.new("RGBA", (W, H), (4, 6, 18, 60)))
    else:
        img = _rgba(t)
    d = ImageDraw.Draw(img)
    d.text((80, 100), spec["kicker"], font=font(MB, 28), fill=t["kicker"])
    _heading(d, sl["heading"], SB, 66, W-160, t["text"], 80, 170)
    bullets = sl["bullets"]; nb = len(bullets)
    top, bottom, gap = 360, 1046, 24
    ch = (bottom - top - (nb-1)*gap)//nb
    y = top
    for b in bullets:
        _glass_r(img, 80, y, W-160, ch, t["card"], outline=(255, 255, 255, 80), radius=24, width=2)
        d = ImageDraw.Draw(img)
        bf = font(SB, 40)
        lines = wrap(d, b, bf, W-260)
        ty = y + (ch - len(lines)*56)//2 + 6
        for ln in lines:
            d.text((115, ty), ln, font=bf, fill=t["text"]); ty += 56
        y += ch + gap
    if sl.get("tag"):
        _aurora_pill(img, t, sl["tag"])
    _verdict_strip(img, t, sl)
    _lockup2(img, t, idx, total, t["text"], t["ring"], t["sub"], num_font=font(M, 26))
    return _finish(img)
def _rich_para(d, text, x, y, max_w, f_body, fill, lh, accent, f_label, label_max=18):
    """Render 'Label: rest...' with the label as a small mono accent line above the body."""
    if ": " in text and len(text.split(": ", 1)[0]) <= label_max:
        lab, rest = text.split(": ", 1)
        d.text((x, y), lab.upper(), font=f_label, fill=accent)
        _track(d, x, y, lab.upper(), f_label, "para-label")
        y += int(lh * 0.84)
        text = rest[:1].upper() + rest[1:]
    for ln in wrap(d, text, f_body, max_w):
        d.text((x, y), ln, font=f_body, fill=fill)
        _track(d, x, y, ln, f_body, "para")
        y += lh
    return y

def _fp_cover(t, spec, total):
    img = _rgba(t); d = ImageDraw.Draw(img)
    # masthead
    d.text((W//2, 58), spec["title"], font=fit(d, spec["title"], SRFB, W-140, 116), fill=t["text"], anchor="ma")
    d.line((80, 208, W-80, 208), fill=t["text"], width=7)
    d.line((80, 222, W-80, 222), fill=t["text"], width=2)
    d.text((W//2, 238), spec["date_line"], font=font(MB, 24), fill=t["sub"], anchor="ma")
    # lead story
    lead = spec["lead"]
    d.text((80, 306), "LEAD STORY", font=font(MB, 27), fill=t["kicker"])
    lt = lead["tag"]; ltf = font(MB, 27)
    d.text((W-80, 306), lt, font=ltf, fill=t["sub"], anchor="ra")
    y = _heading(d, _lead_heading(spec), SB, 78, W-160, t["text"], 80, 350,
                 min_s=40, qa_key="cover_headline_size", label="cover-headline")
    y += 8
    for ln in wrap(d, lead["deck"], font(S, 34), W-160):
        d.text((80, y), ln, font=font(S, 34), fill=t["sub"]); y += 45
    y += 14
    d.line((80, y, W-80, y), fill=t["text"], width=3); y += 30
    d.text((80, y), "ALSO IN TODAY'S DIGEST", font=font(MB, 27), fill=t["kicker"]); y += 46
    for i, c in enumerate(spec["contents"]):
        d.text((80, y), f"{c['n']:02d}", font=font(SB, 38), fill=t["kicker"])
        fit_draw(d, 168, y+2, c["head"], SB, W-168-80, 35, 28, t["text"], label="contents-head")
        fit_draw(d, 168, y+46, c["tease"], S, W-168-80, 28, 21, t["sub"], label="contents-tease")
        y += 88
        if i < len(spec["contents"]) - 1:
            d.line((80, y-12, W-80, y-12), fill=t["hair"], width=1)
    d.text((80, 1140), "SWIPE ->", font=font(MB, 27), fill=t["kicker"])
    _lockup2(img, t, 1, total, t["text"], t["ring"], t["sub"], name_font=font(SB, 28), num_font=font(M, 24))
    return _finish(img)

def _fp_story(t, spec, sl, entry, idx, total):
    img = _rgba(t); d = ImageDraw.Draw(img)
    d.text((80, 92), spec["kicker"], font=font(MB, 24), fill=t["sub"])
    d.text((W-80, 92), sl.get("tag", ""), font=font(MB, 26), fill=t["kicker"], anchor="ra")
    d.line((80, 140, W-80, 140), fill=t["text"], width=3)
    y = _heading(d, sl["heading"], SB, 60, W-160, t["text"], 80, 176)
    d.rectangle((80, y+8, 200, y+15), fill=t["kicker"])
    y += 84
    bf = font(S, 36)
    # Measured balance: pre-measure each rich paragraph, spread slack evenly.
    def _para_h(b):
        body = b
        h = 0
        if ": " in b and len(b.split(": ", 1)[0]) <= 18:
            body = b.split(": ", 1)[1]
            body = body[:1].upper() + body[1:]
            h += int(51 * 0.84)
        return h + len(wrap(d, body, bf, W-160)) * 51
    heights = [_para_h(b) for b in sl["bullets"]]
    total_h = sum(heights) + 26 * len(heights) + 30 * max(0, len(heights) - 1)
    extra = 1046 - y - total_h
    gap = min(extra // max(1, len(heights) - 1), 110) if len(heights) > 1 and extra > 0 else 0
    for i, b in enumerate(sl["bullets"]):
        y = _rich_para(d, b, 80, y, W-160, bf, t["text"], 51, t["kicker"], font(MB, 24))
        y += 26
        if i < len(sl["bullets"]) - 1:
            d.line((80, y, W-80, y), fill=t["hair"], width=1); y += 30 + gap
    _verdict_strip(img, t, sl)
    _lockup2(img, t, idx, total, t["text"], t["ring"], t["sub"], name_font=font(SB, 28), num_font=font(M, 24))
    return _finish(img)

def _fp_recap(t, spec, idx, total):
    img = _rgba(t); d = ImageDraw.Draw(img)
    rec = spec["recap"]
    d.text((80, 84), "AI DEV DIGEST", font=font(SB, 34), fill=t["text"])
    d.text((W-80, 92), spec["kicker"], font=font(MB, 22), fill=t["sub"], anchor="ra")
    d.line((80, 140, W-80, 140), fill=t["text"], width=3)
    d.text((80, 168), "Today in one screen", font=font(SB, 56), fill=t["text"])
    d.text((80, 248), "All five stories, one verdict each — save this screen.", font=font(S, 29), fill=t["sub"])
    y = 322
    for i, (head, verdict) in enumerate(rec["rows"]):
        d.text((80, y), f"{i+1:02d}", font=font(SB, 40), fill=t["kicker"])
        fit_draw(d, 172, y, head, SB, W-172-80, 33, 24, t["text"], label="recap-head")
        vy = y + 46
        fit_draw(d, 172, vy, verdict, S, W-172-80, 28, 20, t["sub"], label="recap-verdict")
        if i < len(rec["rows"]) - 1:
            d.line((80, vy+50, W-80, vy+50), fill=t["hair"], width=1)
        y = vy + 64
    # quotable take block (dark, so the slide survives being forwarded alone)
    d.rounded_rectangle((80, 936, W-80, 1060), radius=18, fill=t["text"])
    fit_draw(d, 116, 960, rec["take"], SRFB, W-232, 37, 24, (255, 255, 255), label="take")
    fit_draw(d, 116, 1010, rec["take_sub"], S, W-232, 25, 19, (198, 200, 208), label="take-sub")
    _lockup2(img, t, idx, total, t["text"], t["ring"], t["sub"], name_font=font(SB, 28), num_font=font(M, 24))
    return _finish(img)

def _fp_cta(t, spec, total, npages):
    img = _rgba(t); d = ImageDraw.Draw(img)
    d.text((W//2, 92), spec["kicker"], font=font(MB, 26), fill=t["kicker"], anchor="ma")
    d.line((80, 148, W-80, 148), fill=t["text"], width=3)
    ph = circle_photo(250); img.paste(ph, ((W-250)//2, 250), ph)
    d = ImageDraw.Draw(img)
    d.ellipse(((W-250)//2-7, 243, (W+250)//2+7, 507), outline=t["ring"], width=5)
    d.text((W//2, 548), _PERSONA_NAME, font=font(SB, 48), fill=t["text"], anchor="ma")
    _pos = _POS_LINE
    d.text((W//2, 616), _pos, font=fit(d, _pos, S, W-160, 31), fill=t["sub"], anchor="ma")
    y = 730
    for ln in spec["cta"]:
        d.text((W//2, y), ln, font=fit(d, ln, SB, W-160, 60), fill=t["text"], anchor="ma"); y += 84
    _lockup2(img, t, npages, total, t["text"], t["ring"], t["sub"], name_font=font(SB, 28), num_font=font(M, 24))
    return _finish(img)

# ---------------- EXPLAINER (Archetype B) ----------------

_LAYOUTS = {
    "frontpage": (_fp_cover, _fp_story, _fp_recap, _fp_cta),
}
# story slides, "Today in one screen" recap, person-led CTA. The skins below
# keep their visual identity but render that full structure from the same
# extended spec (lead / contents / recap fields). Story renderers are reused
# unchanged; cover / recap / CTA are new per skin.

_POS_LINE = "AI architect — I read the firehose so you don't have to."

def _big_avatar(img, t, cx, y, ring):
    """Centered 250px person-led avatar with ring; returns bottom y."""
    ph = circle_photo(250); img.paste(ph, (cx - 125, y), ph)
    d = ImageDraw.Draw(img)
    d.ellipse((cx - 132, y - 7, cx + 132, y + 257), outline=ring, width=5)
    return y + 250

# ---------------- TERMINAL x FRONTPAGE ----------------
def _term_cover2(t, spec, total):
    img = _rgba(t); _term_chrome(img, t); d = ImageDraw.Draw(img)
    d.text((80, 118), "$ cat ai_dev_digest.md", font=font(M, 27), fill=t["dim"])
    d.text((80, 178), "# " + spec["kicker"], font=font(MB, 33), fill=t["kicker"])
    d.text((80, 238), spec["title"], font=fit(d, spec["title"], MB, W-160, 100), fill=t["text"])
    d.line((80, 378, W-80, 378), fill=t["rule_c"], width=2)
    lead = spec["lead"]
    d.text((80, 408), "> LEAD STORY", font=font(MB, 27), fill=t["kicker"])
    d.text((W-80, 408), lead["tag"], font=font(M, 24), fill=t["sub"], anchor="ra")
    y = _heading(d, _lead_heading(spec), MB, 52, W-160, t["text"], 80, 452,
                 min_s=36, qa_key="cover_headline_size", label="cover-headline")
    y += 14
    for ln in wrap(d, lead["deck"], font(M, 26), W-160):
        d.text((80, y), ln, font=font(M, 26), fill=t["sub"]); y += 37
    y += 12
    d.line((80, y, W-80, y), fill=t["rule_c"], width=2); y += 28
    d.text((80, y), "> ALSO IN TODAY'S DIGEST", font=font(MB, 27), fill=t["kicker"]); y += 46
    for c in spec["contents"]:
        d.text((80, y), f"{c['n']:02d}", font=font(MB, 27), fill=t["kicker"])
        fit_draw(d, 158, y, c["head"], MB, W-158-80, 27, 21, t["text"], label="contents-head")
        fit_draw(d, 158, y+38, c["tease"], M, W-158-80, 22, 18, t["dim"], label="contents-tease")
        y += 74
    d.text((80, 1150), "> swipe ->", font=font(MB, 30), fill=t["kicker"])
    _lockup2(img, t, 1, total, t["text"], t["ring"], t["dim"], name_font=font(MB, 28), num_font=font(M, 26))
    return _finish(img)

def _term_recap(t, spec, idx, total):
    img = _rgba(t); _term_chrome(img, t); d = ImageDraw.Draw(img)
    rec = spec["recap"]
    d.text((80, 118), "$ ./recap.sh --today", font=font(M, 27), fill=t["dim"])
    d.text((80, 178), "> Today in one screen", font=font(MB, 46), fill=t["text"])
    d.text((80, 250), "All five stories, one verdict each — save this screen.", font=font(M, 25), fill=t["sub"])
    y = 332
    for i, (head, verdict) in enumerate(rec["rows"]):
        d.text((80, y), f"[{i+1:02d}]", font=font(MB, 28), fill=t["kicker"])
        fit_draw(d, 212, y, head, MB, W-212-80, 28, 21, t["text"], label="recap-head")
        fit_draw(d, 212, y+42, verdict, M, W-212-80, 24, 19, t["sub"], label="recap-verdict")
        y += 94
        if i < len(rec["rows"]) - 1:
            d.line((80, y-15, W-80, y-15), fill=t["rule_c"], width=1)
    d.rectangle((80, 830, W-80, 1002), outline=t["kicker"], width=2)
    fit_draw(d, 116, 862, rec["take"], MB, W-232, 34, 22, t["text"], label="take")
    fit_draw(d, 116, 924, rec["take_sub"], M, W-232, 24, 19, t["sub"], label="take-sub")
    d.text((80, 1044), "# EOF — recap complete", font=font(M, 24), fill=t["dim"])
    _lockup2(img, t, idx, total, t["text"], t["ring"], t["dim"], name_font=font(MB, 28), num_font=font(M, 26))
    return _finish(img)

def _term_cta2(t, spec, total, npages):
    img = _rgba(t); _term_chrome(img, t); d = ImageDraw.Draw(img)
    d.text((80, 130), "$ whoami", font=font(M, 28), fill=t["dim"])
    _big_avatar(img, t, W//2, 210, t["ring"])
    d = ImageDraw.Draw(img)
    d.text((W//2, 512), _PERSONA_NAME, font=font(MB, 44), fill=t["text"], anchor="ma")
    d.text((W//2, 580), _POS_LINE, font=fit(d, _POS_LINE, M, W-160, 26, min_s=20), fill=t["sub"], anchor="ma")
    y = 692
    for i, ln in enumerate(spec["cta"]):
        col = t["kicker"] if i == len(spec["cta"]) - 1 else t["text"]
        d.text((W//2, y), ln, font=fit(d, ln, MB, W-200, 56), fill=col, anchor="ma"); y += 84
    d.text((W//2, y+28), "# EOF — exit 0", font=font(M, 26), fill=t["dim"], anchor="ma")
    _lockup2(img, t, npages, total, t["text"], t["ring"], t["dim"], name_font=font(MB, 28), num_font=font(M, 26))
    return _finish(img)

# ---------------- NEON GRID x FRONTPAGE ----------------
def _neon_cover2(t, spec, total):
    img = _neon_bg(t, spec); d = ImageDraw.Draw(img)
    d.text((80, 90), spec["kicker"], font=font(MB, 32), fill=t["kicker"])
    bar = _hgrad(260, 10, t["kicker"], t["accent2"]).convert("RGBA"); img.paste(bar, (80, 140), bar)
    d = ImageDraw.Draw(img)
    d.text((80, 180), spec["title"], font=fit(d, spec["title"], SB, W-160, 118), fill=t["text"])
    lead = spec["lead"]
    _neon_panel(img, t, 80, 350, W-160, 372)
    d = ImageDraw.Draw(img)
    d.text((112, 382), "LEAD STORY", font=font(MB, 26), fill=t["kicker"])
    d.text((W-112, 382), lead["tag"], font=font(MB, 24), fill=t["accent2"], anchor="ra")
    y = _heading(d, _lead_heading(spec), SB, 54, W-224, t["text"], 112, 428,
                 min_s=40, qa_key="cover_headline_size", label="cover-headline")
    y += 10
    for ln in wrap(d, lead["deck"], font(S, 29), W-224):
        d.text((112, y), ln, font=font(S, 29), fill=t["sub"]); y += 40
    d.text((80, 772), "ALSO IN TODAY'S DIGEST", font=font(MB, 26), fill=t["kicker"])
    y = 820
    for c in spec["contents"]:
        d.text((80, y), f"{c['n']:02d}", font=font(SB, 32), fill=t["accent2"])
        fit_draw(d, 158, y+1, c["head"], SB, W-158-80, 31, 25, t["text"], label="contents-head")
        fit_draw(d, 158, y+42, c["tease"], S, W-158-80, 25, 20, t["sub"], label="contents-tease")
        y += 74
    d.text((80, 1150), "swipe  ->", font=font(SB, 32), fill=t["text"])
    _lockup2(img, t, 1, total, t["text"], t["ring"], t["kicker"], num_font=font(M, 26))
    return _finish(img)

def _neon_recap(t, spec, idx, total):
    img = _neon_bg(t, spec); d = ImageDraw.Draw(img)
    rec = spec["recap"]
    d.text((80, 88), spec["kicker"], font=font(MB, 26), fill=t["kicker"])
    d.text((80, 140), "Today in one screen", font=font(SB, 56), fill=t["text"])
    d.text((80, 222), "All five stories, one verdict each — save this screen.", font=font(S, 27), fill=t["sub"])
    y = 300
    for i, (head, verdict) in enumerate(rec["rows"]):
        _neon_panel(img, t, 80, y, W-160, 100)
        d = ImageDraw.Draw(img)
        d.text((112, y+30), f"{i+1:02d}", font=font(SB, 32), fill=t["accent2"])
        fit_draw(d, 196, y+16, head, SB, W-196-96, 30, 24, t["text"], label="recap-head")
        fit_draw(d, 196, y+56, verdict, S, W-196-96, 24, 19, t["sub"], label="recap-verdict")
        y += 116
    _glass_r(img, 80, 896, W-160, 150, t["card"], outline=tuple(list(t["accent2"]) + [200]), radius=24, width=2)
    d = ImageDraw.Draw(img)
    fit_draw(d, 112, 924, rec["take"], SB, W-224, 36, 22, t["text"], label="take")
    fit_draw(d, 112, 978, rec["take_sub"], S, W-224, 25, 20, t["sub"], label="take-sub")
    _lockup2(img, t, idx, total, t["text"], t["ring"], t["kicker"], num_font=font(M, 26))
    return _finish(img)

def _neon_cta2(t, spec, total, npages):
    img = _neon_bg(t, spec); d = ImageDraw.Draw(img)
    d.text((80, 90), spec["kicker"], font=font(MB, 30), fill=t["kicker"])
    bar = _hgrad(260, 10, t["kicker"], t["accent2"]).convert("RGBA"); img.paste(bar, (80, 138), bar)
    _big_avatar(img, t, W//2, 215, t["ring"])
    d = ImageDraw.Draw(img)
    d.text((W//2, 517), _PERSONA_NAME, font=font(SB, 48), fill=t["text"], anchor="ma")
    d.text((W//2, 585), _POS_LINE, font=fit(d, _POS_LINE, S, W-160, 29, min_s=22), fill=t["sub"], anchor="ma")
    y = 722
    for i, ln in enumerate(spec["cta"]):
        col = t["accent2"] if i == len(spec["cta"]) - 1 else t["text"]
        d.text((80, y), ln, font=fit(d, ln, SB, W-160, 80), fill=col); y += 116
    _lockup2(img, t, npages, total, t["text"], t["ring"], t["kicker"], num_font=font(M, 26))
    return _finish(img)

# ---------------- BOLD POSTER x FRONTPAGE ----------------
def _poster_cover2(t, spec, total):
    img = _rgba(t); d = ImageDraw.Draw(img)
    acc = t["kicker"]
    import re as _re
    m = _re.search(r"#(\d+)", spec["kicker"])
    ed = f"{int(m.group(1)):02d}" if m else "01"
    ghost = _blend(acc, t["bg"][0], 0.14)
    d.text((W-370, 56), ed, font=font(SB, 240), fill=ghost)
    d.rectangle((80, 104, 100, 124), fill=acc)
    d.text((116, 96), spec["kicker"], font=font(MB, 28), fill=t["text"])
    d.text((74, 168), spec["title"], font=fit(d, spec["title"], SB, W-148, 148), fill=t["text"])
    d.rectangle((80, 352, 470, 380), fill=acc)
    lead = spec["lead"]
    d.text((80, 408), "LEAD STORY", font=font(MB, 26), fill=acc)
    d.text((W-80, 408), lead["tag"], font=font(MB, 24), fill=t["sub"], anchor="ra")
    y = _heading(d, _lead_heading(spec), SB, 54, W-160, t["text"], 80, 452,
                 min_s=40, qa_key="cover_headline_size", label="cover-headline")
    y += 12
    for ln in wrap(d, lead["deck"], font(S, 29), W-160):
        d.text((80, y), ln, font=font(S, 29), fill=t["sub"]); y += 40
    y += 8
    d.line((80, y, W-80, y), fill=t["text"], width=3); y += 28
    d.text((80, y), "ALSO IN TODAY'S DIGEST", font=font(MB, 26), fill=acc); y += 44
    for c in spec["contents"]:
        d.text((80, y), f"{c['n']:02d}", font=font(SB, 30), fill=acc)
        fit_draw(d, 158, y+1, c["head"], SB, W-158-80, 30, 24, t["text"], label="contents-head")
        fit_draw(d, 158, y+40, c["tease"], S, W-158-80, 24, 19, t["sub"], label="contents-tease")
        y += 72
    d.text((80, 1150), "SWIPE ->", font=font(MB, 30), fill=t["text"])
    _lockup2(img, t, 1, total, t["text"], t["ring"], t["text"], num_font=font(SB, 32), num_xy=(80, H-124))
    return _finish(img)

def _poster_recap(t, spec, idx, total):
    img = _rgba(t); d = ImageDraw.Draw(img)
    acc = t["kicker"]
    rec = spec["recap"]
    d.rectangle((0, 0, 110, H), fill=acc)
    d.text((W-80, 84), spec["kicker"], font=font(MB, 22), fill=t["sub"], anchor="ra")
    d.text((190, 104), "AI DEV DIGEST — RECAP", font=font(MB, 26), fill=acc)
    _heading(d, "Today in one screen", SB, 68, W-190-70, t["text"], 190, 148)
    d.text((190, 256), "All five stories, one verdict each — save this screen.",
           font=fit(d, "All five stories, one verdict each — save this screen.", S, W-190-70, 27, min_s=21), fill=t["sub"])
    accents = [t["slot_accents"].get(k, acc) for k in ("PRODUCT", "FRAMEWORKS", "REPO", "RESEARCH", "ECOSYSTEM")]
    y = 330
    for i, (head, verdict) in enumerate(rec["rows"]):
        a = accents[i % len(accents)]
        d.text((190, y), f"{i+1:02d}", font=font(SB, 58), fill=a)
        fit_draw(d, 330, y+4, head, SB, W-330-70, 32, 25, t["text"], label="recap-head")
        fit_draw(d, 330, y+48, verdict, S, W-330-70, 25, 20, t["sub"], label="recap-verdict")
        y += 104
        if i < len(rec["rows"]) - 1:
            d.line((190, y-22, W-70, y-22), fill=t["text"], width=1)
    d.rectangle((190, 872, W-70, 1010), fill=t["text"])
    fit_draw(d, 226, 900, rec["take"], SB, W-70-190-72, 36, 22, (255, 255, 255), label="take")
    fit_draw(d, 226, 954, rec["take_sub"], S, W-70-190-72, 24, 19, (198, 200, 208), label="take-sub")
    _lockup2(img, t, idx, total, t["text"], t["ring"], t["text"], num_font=font(SB, 32), num_xy=(190, H-124))
    return _finish(img)

def _poster_cta2(t, spec, total, npages):
    img = _rgba(t); d = ImageDraw.Draw(img)
    acc = t["kicker"]
    d.rectangle((0, 0, 110, H), fill=acc)
    d.text((190, 96), spec["kicker"], font=font(MB, 26), fill=t["text"])
    ph = circle_photo(250); img.paste(ph, (190, 190), ph)
    d = ImageDraw.Draw(img)
    d.ellipse((183, 183, 447, 447), outline=t["ring"], width=5)
    d.text((190, 486), _PERSONA_NAME, font=font(SB, 52), fill=t["text"])
    d.text((190, 556), _POS_LINE, font=fit(d, _POS_LINE, S, W-190-70, 29, min_s=22), fill=t["sub"])
    y = 680
    for i, ln in enumerate(spec["cta"]):
        col = acc if i == len(spec["cta"]) - 1 else t["text"]
        d.text((190, y), ln, font=fit(d, ln, SB, W-190-70, 80), fill=col); y += 116
    ay = y + 24
    d.rectangle((190, ay, 360, ay+26), fill=acc)
    d.polygon([(360, ay-20), (360, ay+46), (436, ay+13)], fill=acc)
    _lockup2(img, t, npages, total, t["text"], t["ring"], t["text"], num_font=font(SB, 32), num_xy=(190, H-124))
    return _finish(img)

# ---------------- AURORA x FRONTPAGE ----------------
def _aurora_cover2(t, spec, total):
    img = _rgba(t); d = ImageDraw.Draw(img)
    d.text((80, 96), spec["kicker"], font=font(MB, 32), fill=t["kicker"])
    d.text((80, 178), spec["title"], font=fit(d, spec["title"], SB, W-160, 118), fill=t["text"])
    lead = spec["lead"]
    _glass_r(img, 80, 348, W-160, 374, t["card"], outline=(255, 255, 255, 110), radius=30, width=2)
    d = ImageDraw.Draw(img)
    d.text((112, 380), "LEAD STORY", font=font(MB, 26), fill=t["kicker"])
    d.text((W-112, 380), lead["tag"], font=font(MB, 24), fill=t["sub"], anchor="ra")
    y = _heading(d, _lead_heading(spec), SB, 54, W-224, t["text"], 112, 426,
                 min_s=40, qa_key="cover_headline_size", label="cover-headline")
    y += 10
    for ln in wrap(d, lead["deck"], font(S, 29), W-224):
        d.text((112, y), ln, font=font(S, 29), fill=t["sub"]); y += 40
    d.text((80, 770), "ALSO IN TODAY'S DIGEST", font=font(MB, 26), fill=t["kicker"])
    y = 818
    for c in spec["contents"]:
        d.text((80, y), f"{c['n']:02d}", font=font(SB, 32), fill=t["kicker"])
        fit_draw(d, 158, y+1, c["head"], SB, W-158-80, 31, 25, t["text"], label="contents-head")
        fit_draw(d, 158, y+42, c["tease"], S, W-158-80, 25, 20, t["sub"], label="contents-tease")
        y += 74
    d.text((80, 1150), "swipe  ->", font=font(SB, 32), fill=t["text"])
    _lockup2(img, t, 1, total, t["text"], t["ring"], t["sub"], num_font=font(M, 26))
    return _finish(img)

def _aurora_recap(t, spec, idx, total):
    img = _rgba(t); d = ImageDraw.Draw(img)
    rec = spec["recap"]
    d.text((80, 88), spec["kicker"], font=font(MB, 26), fill=t["kicker"])
    d.text((80, 140), "Today in one screen", font=font(SB, 56), fill=t["text"])
    d.text((80, 222), "All five stories, one verdict each — save this screen.", font=font(S, 27), fill=t["sub"])
    y = 300
    for i, (head, verdict) in enumerate(rec["rows"]):
        _glass_r(img, 80, y, W-160, 100, t["card"], outline=(255, 255, 255, 80), radius=24, width=2)
        d = ImageDraw.Draw(img)
        d.text((112, y+30), f"{i+1:02d}", font=font(SB, 32), fill=t["kicker"])
        fit_draw(d, 196, y+16, head, SB, W-196-96, 30, 24, t["text"], label="recap-head")
        fit_draw(d, 196, y+56, verdict, S, W-196-96, 24, 19, t["sub"], label="recap-verdict")
        y += 116
    _glass_r(img, 80, 896, W-160, 150, t["card"], outline=tuple(list(t["kicker"]) + [200]), radius=24, width=2)
    d = ImageDraw.Draw(img)
    fit_draw(d, 112, 924, rec["take"], SB, W-224, 36, 22, t["text"], label="take")
    fit_draw(d, 112, 978, rec["take_sub"], S, W-224, 25, 20, t["sub"], label="take-sub")
    _lockup2(img, t, idx, total, t["text"], t["ring"], t["sub"], num_font=font(M, 26))
    return _finish(img)

def _aurora_cta2(t, spec, total, npages):
    img = _rgba(t); d = ImageDraw.Draw(img)
    d.text((80, 96), spec["kicker"], font=font(MB, 30), fill=t["kicker"])
    _big_avatar(img, t, W//2, 215, t["ring"])
    d = ImageDraw.Draw(img)
    d.text((W//2, 517), _PERSONA_NAME, font=font(SB, 48), fill=t["text"], anchor="ma")
    d.text((W//2, 585), _POS_LINE, font=fit(d, _POS_LINE, S, W-160, 29, min_s=22), fill=t["sub"], anchor="ma")
    y = 722
    for i, ln in enumerate(spec["cta"]):
        col = t["kicker"] if i == len(spec["cta"]) - 1 else t["text"]
        d.text((80, y), ln, font=fit(d, ln, SB, W-160, 80), fill=col); y += 116
    _lockup2(img, t, npages, total, t["text"], t["ring"], t["sub"], num_font=font(M, 26))
    return _finish(img)

_LAYOUTS.update({
    "terminal": (_term_cover2, _term_story, _term_recap, _term_cta2),
    "neon": (_neon_cover2, _neon_story, _neon_recap, _neon_cta2),
    "poster": (_poster_cover2, _poster_story, _poster_recap, _poster_cta2),
    "aurora": (_aurora_cover2, _aurora_story, _aurora_recap, _aurora_cta2),
})


# ---------------------------------------------------------------------------
# Prism entry point (keeps the FastMCP render_carousel interface)
# ---------------------------------------------------------------------------

def _normalize_legacy(spec):
    """Accept the pre-v3 spec ({title, subtitle, slides:[{heading, bullets}]})
    and lift it into the v3 schema so older callers never crash."""
    slides = spec.get("slides") or []
    stories = [{"heading": s.get("heading", ""), "tag": s.get("tag", ""),
                "bullets": list(s.get("bullets") or [])[:3],
                "verdict": s.get("verdict", "")} for s in slides[:5]]
    lead_src = stories[0] if stories else {"heading": spec.get("title", "Untitled"), "bullets": []}
    return {
        "kicker": spec.get("brand", "PRISM").upper(),
        "title": spec.get("title", "Prism Digest"),
        "date_line": "",
        "cover_sub": spec.get("subtitle", ""),
        "lead": {"heading": lead_src.get("heading", ""), "deck": (lead_src.get("bullets") or [""])[0],
                 "tag": lead_src.get("tag", "")},
        "contents": [{"n": i + 2, "head": s["heading"], "tease": (s["bullets"] or [""])[0]}
                     for i, s in enumerate(stories[1:])],
        "slides": stories,
        "recap": {"rows": [[s["heading"], s.get("verdict", "")] for s in stories],
                  "take": "", "take_sub": ""},
        "cta": ["Follow so you don't miss it."],
        "skin": spec.get("skin", "frontpage"),
        "edition": spec.get("edition", 1),
    }


def render_carousel(spec: dict, output_dir: str) -> dict:
    """Render the v3 8-page carousel. Returns {pdf_path, png_paths,
    slide_count, skin, edition}. Exactly 8 pages: cover + 5 stories +
    recap + CTA — missing stories are padded, extras truncated."""
    global _PERSONA_NAME, _PERSONA_PHOTO, _POS_LINE
    os.makedirs(output_dir, exist_ok=True)
    if "lead" not in spec:
        spec = _normalize_legacy(spec)
    persona = spec.get("persona") or {}
    _PERSONA_NAME = persona.get("name") or _PERSONA_NAME
    _PERSONA_PHOTO = persona.get("photo") or ""
    if persona.get("position"):
        _POS_LINE = persona["position"]

    skin = spec.get("skin") or skin_for_edition(int(spec.get("edition", 1)))
    theme = THEMES.get(skin, THEMES["frontpage"])
    layout = _LAYOUTS[theme["layout"]]
    cover_f, story_f, recap_f, cta_f = layout

    stories = list(spec.get("slides") or [])[:5]
    rows = (spec.get("recap") or {}).get("rows") or []
    while len(stories) < 5:  # structural guarantee: always 5 story slides
        i = len(stories)
        head = rows[i][0] if i < len(rows) else f"Story {i + 1}"
        stories.append({"heading": head, "tag": "", "bullets": [], "verdict": ""})
    if skin not in BROLL_SKINS:  # v3 b-roll rule: neon-grid / aurora only
        for s in stories:
            s.pop("broll", None)

    _reset_qa()
    total = 8
    pages = []

    def _mk(fn, *args):
        _PAGE[0] = len(pages) + 1
        pages.append(fn(*args))

    _mk(cover_f, theme, spec, total)
    for i, sl in enumerate(stories):
        _mk(story_f, theme, spec, sl, i + 1, i + 2, total)
    _mk(recap_f, theme, spec, len(pages) + 1, total)
    _mk(cta_f, theme, spec, total, len(pages) + 1)
    assert len(pages) == 8, f"v3 carousel must be 8 pages, got {len(pages)}"

    # QA gate: photo (not monogram), real bundled fonts, headline at/above
    # the floor, zero tracked text-block intersections, exactly 8 pages.
    overlaps = sum(_page_overlaps(p) for p in range(1, total + 1))
    out_of_bounds = sum(1 for b in _BOXES if b[1] < -2 or b[3] > W + 2)
    qa = {"avatar": _QA["avatar"] or "monogram",
          "fonts_ok": bool(_QA["fonts_ok"]),
          "cover_headline_size": _QA["cover_headline_size"],
          "headline_floor": HEADLINE_FLOOR,
          "overlaps": overlaps,
          "out_of_bounds": out_of_bounds,
          "slide_count": len(pages)}
    qa["passed"] = bool(qa["avatar"] == "photo" and qa["fonts_ok"]
                        and (qa["cover_headline_size"] or 0) >= HEADLINE_FLOOR
                        and overlaps == 0 and out_of_bounds == 0
                        and len(pages) == 8)

    png_paths = []
    for idx, page in enumerate(pages):
        p = os.path.join(output_dir, f"slide-{idx + 1:02d}.png")
        page.save(p, "PNG")
        png_paths.append(p)
    pdf_path = os.path.join(output_dir, "carousel.pdf")
    pages[0].save(pdf_path, "PDF", save_all=True, append_images=pages[1:], resolution=144)
    return {"pdf_path": pdf_path, "png_paths": png_paths,
            "slide_count": len(png_paths), "skin": skin,
            "edition": spec.get("edition"), "qa": qa}
