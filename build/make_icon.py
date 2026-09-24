"""Generate the app icon for Claude Multi-Instance Setup in every format the
build scripts need: icon.ico (Windows), icon.icns (macOS), icon.png (Linux)."""

import os

from PIL import Image, ImageDraw


def draw(sz: int) -> Image.Image:
    """Stacked rounded rectangles suggesting "multiple instances"."""
    img = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = max(1, int(sz * 0.06))
    d.rounded_rectangle([pad, pad, sz - pad, sz - pad], radius=max(2, int(sz * 0.2)),
                        fill=(22, 26, 34, 255))

    def rr(y_off: float, height: float, col: tuple) -> None:
        x1, x2 = int(sz * 0.2), sz - int(sz * 0.2)
        y1, y2 = int(sz * y_off), int(sz * (y_off + height))
        d.rounded_rectangle([x1, y1, x2, y2], radius=max(1, int(sz * 0.06)), fill=col)

    rr(0.22, 0.26, (60, 50, 45, 255))     # back layer (muted)
    rr(0.37, 0.26, (100, 70, 50, 255))    # middle layer
    rr(0.52, 0.26, (217, 119, 87, 255))   # front layer (accent)
    return img


def make_all(root: str) -> None:
    sizes = [16, 24, 32, 48, 64, 128, 256]
    frames = [draw(s) for s in sizes]
    frames[-1].save(os.path.join(root, "icon.ico"), format="ICO",
                    sizes=[(s, s) for s in sizes], append_images=frames[:-1])
    draw(1024).save(os.path.join(root, "icon.icns"), format="ICNS")
    draw(512).save(os.path.join(root, "icon.png"), format="PNG")
    print(f"icons saved in {root}: icon.ico, icon.icns, icon.png")


if __name__ == "__main__":
    make_all(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
