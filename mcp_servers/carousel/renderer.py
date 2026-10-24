"""Prism carousel renderer — PIL, 1080x1350, light aurora style.

Shared module: imported directly by the agent's makers AND exposed over MCP
by server.py in this folder. Bullets are hard-capped at 125 chars (standing
carousel QA rule: longer bullets silently lose their tail when rendered).
"""
from __future__ import annotations

import os
import textwrap

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1350
PORCELAIN = (247, 249, 250)
INK = (11, 21, 38)
MUTED = (84, 96, 120)
MAX_BULLET = 125

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def gradient_band(img: Image.Image, y0: int, y1: int, c1, c2) -> None:
    draw = ImageDraw.Draw(img)
    for y in range(y0, y1):
        t = (y - y0) / max(1, (y1 - y0))
        # horizontal sweep too, for an aurora feel
        draw.line([(0, y), (W, y)], fill=_lerp(c1, c2, t * 0.7))


def _split_long_word(draw, word, font, max_w):
    """Split a single word (e.g. a URL) that is wider than the line."""
    chunks, cur = [], ""
    for ch in word:
        if draw.textlength(cur + ch, font=font) <= max_w:
            cur += ch
        else:
            if cur:
                chunks.append(cur)
            cur = ch
    if cur:
        chunks.append(cur)
    return chunks


def _wrap(draw, text, font, max_w):
    words, lines, cur = [], [], ""
    expanded = []
    for w_ in text.split():
        if draw.textlength(w_, font=font) > max_w:
            expanded.extend(_split_long_word(draw, w_, font, max_w))
        else:
            expanded.append(w_)
    words = expanded
    for w_ in words:
        trial = (cur + " " + w_).strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w_
    if cur:
        lines.append(cur)
    return lines


def render_carousel(spec: dict, output_dir: str) -> dict:
    """spec: {title, subtitle, brand, theme:{start,end,accent}, slides:[{heading, bullets[]}]}
    Returns {pdf_path, png_paths, slide_count}."""
    os.makedirs(output_dir, exist_ok=True)
    theme = spec.get("theme") or {}
    c1 = hex_to_rgb(theme.get("start", "#38BDF8"))
    c2 = hex_to_rgb(theme.get("end", "#7C6CF0"))
    accent = hex_to_rgb(theme.get("accent", "#7C6CF0"))
    brand = spec.get("brand", "PRISM")
    slides = []
    # Cover
    slides.append({"cover": True, "heading": spec.get("title", "Untitled"),
                   "bullets": [spec.get("subtitle", "")] if spec.get("subtitle") else []})
    slides.extend(spec.get("slides") or [])

    png_paths = []
    images = []
    total = len(slides)
    for idx, slide in enumerate(slides):
        img = Image.new("RGB", (W, H), PORCELAIN)
        d = ImageDraw.Draw(img)
        if slide.get("cover"):
            gradient_band(img, 0, 760, c1, c2)
            d = ImageDraw.Draw(img)
            d.text((64, 84), brand.upper(), font=_font(FONT_BOLD, 34), fill=(255, 255, 255))
            y = 220
            for line in _wrap(d, slide["heading"], _font(FONT_BOLD, 76), W - 128):
                d.text((64, y), line, font=_font(FONT_BOLD, 76), fill=(255, 255, 255))
                y += 96
            if slide["bullets"]:
                y += 30
                for line in _wrap(d, slide["bullets"][0], _font(FONT_REGULAR, 38), W - 128)[:3]:
                    if y > 700:
                        break
                    d.text((64, y), line, font=_font(FONT_REGULAR, 38), fill=(240, 248, 255))
                    y += 52
        else:
            d.rectangle([0, 0, W, 18], fill=accent)
            d.text((64, 60), brand.upper(), font=_font(FONT_BOLD, 28), fill=accent)
            y = 150
            for line in _wrap(d, slide.get("heading", ""), _font(FONT_BOLD, 58), W - 128):
                d.text((64, y), line, font=_font(FONT_BOLD, 58), fill=INK)
                y += 74
            y += 28
            bf = _font(FONT_REGULAR, 37)
            for bullet in slide.get("bullets", []):
                b = (bullet or "").strip()
                if len(b) > MAX_BULLET:
                    b = b[: MAX_BULLET - 1].rstrip() + "…"
                if not b:
                    continue
                d.ellipse([64, y + 14, 78, y + 28], fill=accent)
                for j, line in enumerate(_wrap(d, b, bf, W - 190)):
                    d.text((104, y), line, font=bf, fill=INK if j == 0 else MUTED)
                    y += 50
                y += 26
                if y > H - 160:
                    break
        d = ImageDraw.Draw(img)
        d.text((64, H - 72), f"{idx + 1} / {total}", font=_font(FONT_REGULAR, 26), fill=MUTED)
        p = os.path.join(output_dir, f"slide-{idx + 1:02d}.png")
        img.save(p, "PNG")
        png_paths.append(p)
        images.append(img.copy())

    pdf_path = os.path.join(output_dir, "carousel.pdf")
    if images:
        images[0].save(pdf_path, "PDF", save_all=True, append_images=images[1:], resolution=144)
    return {"pdf_path": pdf_path, "png_paths": png_paths, "slide_count": len(png_paths)}
