"""Per-instance icons: Claude's starburst on a colored tile, plus an optional
1-2 letter badge, so each instance is recognizable at a glance.

Needs Pillow. Without it icons are skipped and launchers keep Claude's icon.
"""

from __future__ import annotations

import math
import os
from functools import lru_cache

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFont
except Exception:  # noqa: BLE001
    Image = None  # type: ignore[assignment]

# (label, hex). The first entry is Claude's own coral, so it is not used as a
# default: extra instances should look different from the original.
PALETTE = [
    ("Coral", "#D97757"),
    ("Blue", "#2F6FEB"),
    ("Green", "#1A9A4B"),
    ("Purple", "#8250DF"),
    ("Pink", "#D6336C"),
    ("Teal", "#0E8A83"),
    ("Amber", "#D98E04"),
    ("Red", "#CF222E"),
    ("Indigo", "#4B4FD6"),
    ("Slate", "#4A5568"),
    ("Black", "#1F2328"),
]

_ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def available() -> bool:
    return Image is not None


def default_color(index: int) -> str:
    """Palette color for the index-th extra instance (skips Claude's coral)."""
    choices = PALETTE[1:]
    return choices[index % len(choices)][1]


def default_badge(name: str) -> str:
    """'Work' -> 'W', 'Instance 2' -> 'I2', 'Personal Gmail' -> 'PG'."""
    words = [w for w in name.replace("-", " ").replace("_", " ").split() if w]
    return "".join(w[0] for w in words[:2]).upper()


def normalize_color(value: str) -> str | None:
    v = (value or "").strip()
    if not v.startswith("#"):
        v = "#" + v
    if len(v) == 4:
        v = "#" + "".join(c * 2 for c in v[1:])
    try:
        int(v[1:], 16)
    except ValueError:
        return None
    return v.upper() if len(v) == 7 else None


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _is_light(rgb: tuple[int, int, int]) -> bool:
    r, g, b = (c / 255 for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.62


def claude_icon_source(resources_dir: str | None) -> str | None:
    """Claude's own app icon inside an install's resources dir, if present."""
    if not resources_dir:
        return None
    p = os.path.join(resources_dir, "ion-dist", "images", "claude_app_icon.png")
    return p if os.path.isfile(p) else None


@lru_cache(maxsize=8)
def _starburst_mask(size: int, source_png: str | None):
    """Alpha mask of Claude's starburst, from the real icon when available."""
    if source_png:
        try:
            src = Image.open(source_png).convert("RGB")
            # the starburst is coral (R-B ~130); the cream tile and its grey
            # frame are near-neutral (R-B ~20 or less), so key on R-B
            r, _g, b = src.split()
            mask = ImageChops.subtract(r, b).point(lambda v: max(0, min(255, (v - 30) * 255 // 90)))
            bbox = mask.point(lambda v: 255 if v > 40 else 0).getbbox()
            if bbox:
                return mask.crop(bbox)
        except Exception:  # noqa: BLE001
            pass
    # fallback: a drawn 12-ray burst
    s = size * 4
    img = Image.new("L", (s, s), 0)
    d = ImageDraw.Draw(img)
    c = s / 2
    for i in range(12):
        a = i * math.pi / 6 + 0.13
        r = s * (0.48 if i % 2 == 0 else 0.40)
        d.line([(c, c), (c + r * math.cos(a), c + r * math.sin(a))], fill=255, width=int(s * 0.07))
    return img


def _font(px: int):
    for path in _FONT_CANDIDATES:
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, px)
            except Exception:  # noqa: BLE001
                continue
    try:
        return ImageFont.load_default(size=px)
    except TypeError:
        return ImageFont.load_default()


def render(color: str, badge: str = "", size: int = 256, source_png: str | None = None):
    """Return an RGBA PIL image for the given color/badge."""
    if Image is None:
        raise RuntimeError("Pillow is not installed")
    scale = 4  # supersample for smooth edges
    s = size * scale
    rgb = _rgb(normalize_color(color) or PALETTE[1][1])
    fg = (31, 35, 40) if _is_light(rgb) else (255, 255, 255)

    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = int(s * 0.04)
    d.rounded_rectangle([pad, pad, s - pad, s - pad], radius=int(s * 0.22), fill=rgb + (255,))

    badge = (badge or "").strip()[:2]
    burst = int(s * (0.52 if badge else 0.64))
    mask = _starburst_mask(size if not source_png else 0, source_png).resize((burst, burst), Image.LANCZOS)
    cx = cy = s // 2
    if badge:
        cx, cy = int(s * 0.42), int(s * 0.42)
    img.paste(Image.new("RGBA", (burst, burst), fg + (255,)), (cx - burst // 2, cy - burst // 2), mask)

    if badge:
        r = int(s * 0.25)
        bx, by = int(s * 0.70), int(s * 0.70)
        d.ellipse([bx - r - pad, by - r - pad, bx + r + pad, by + r + pad], fill=rgb + (255,))
        d.ellipse([bx - r, by - r, bx + r, by + r], fill=fg + (255,))
        font = _font(int(r * (1.15 if len(badge) == 1 else 0.85)))
        d.text((bx, by), badge.upper(), fill=rgb + (255,), font=font, anchor="mm")

    return img.resize((size, size), Image.LANCZOS)


def write_icon(path: str, color: str, badge: str = "", source_png: str | None = None) -> str:
    """Write .ico (Windows), .icns (macOS) or .png depending on the extension."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img = render(color, badge, 256 if not path.endswith(".icns") else 512, source_png)
    if path.endswith(".ico"):
        # each size rendered on its own; the badge is unreadable at 16px
        frames = [render(color, badge if w > 16 else "", w, source_png) for w, _h in _ICO_SIZES[:-1]]
        img.save(path, format="ICO", sizes=_ICO_SIZES, append_images=frames)
    elif path.endswith(".icns"):
        img.save(path, format="ICNS")
    else:
        img.save(path, format="PNG")
    return path
