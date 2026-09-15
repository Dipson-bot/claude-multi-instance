"""Generate a multi-resolution .ico icon for Claude Multi-Instance Setup."""

from PIL import Image, ImageDraw

def make_icon(path: str) -> None:
    sizes = [16, 32, 48, 64, 128, 256]
    imgs: list[Image.Image] = []
    for sz in sizes:
        img = Image.new("RGBA", (sz, sz), (15, 17, 21, 255))
        d = ImageDraw.Draw(img)
        m = sz / 2

        # background rounded rect (dark charcoal)
        pad = max(1, int(sz * 0.12))
        r = max(2, int(sz * 0.18))
        d.rounded_rectangle(
            [pad, pad, sz - pad, sz - pad],
            radius=r,
            fill=(22, 26, 34, 255),
        )

        # stacked rounded rects to suggest "multiple instances"
        def rr(y_off: float, height: float, col: tuple) -> None:
            x1 = pad + int(sz * 0.18)
            x2 = sz - pad - int(sz * 0.18)
            y1 = pad + int(sz * y_off)
            y2 = pad + int(sz * (y_off + height))
            cr = max(1, int(sz * 0.06))
            d.rounded_rectangle([x1, y1, x2, y2], radius=cr, fill=col)

        # back layer (muted)
        rr(0.22, 0.26, (60, 50, 45, 220))
        # middle layer
        rr(0.36, 0.26, (100, 70, 50, 235))
        # front layer (accent)
        rr(0.50, 0.26, (217, 119, 87, 255))

        imgs.append(img)

    imgs[0].save(path, format="ICO", sizes=[(s, s) for s in sizes], append_images=imgs[1:])
    print(f"icon saved: {path}")


if __name__ == "__main__":
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    make_icon(os.path.join(root, "icon.ico"))
