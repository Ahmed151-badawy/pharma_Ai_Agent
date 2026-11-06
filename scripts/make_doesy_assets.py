"""Build the Doesy asset set from the supplied cut-out. Usage: make_doesy_assets.py SRC OUTDIR"""
import base64
import io
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage as ndi

src, out = Path(sys.argv[1]), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)

# ---- 1. clean the cut-out -------------------------------------------------------------------
im = np.array(Image.open(src).convert("RGBA"))
alpha = im[..., 3].copy()
alpha[alpha < 12] = 0                                   # kill the faint speckle haze
labels, n = ndi.label(alpha > 0)
sizes = ndi.sum(alpha > 0, labels, range(1, n + 1))
keep = np.isin(labels, [i + 1 for i, s in enumerate(sizes) if s > 2000])   # body + 3 spark marks only
alpha[~keep] = 0
im[..., 3] = alpha
im[alpha == 0, :3] = 0
ys, xs = np.where(alpha > 0)
x0, y0, x1, y1 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
print("removed fragments:", n - int(sum(s > 2000 for s in sizes)), "| content bbox", (x0, y0, x1, y1))
master = Image.fromarray(im)


def trim(img, pad=0.03):
    a = np.array(img)[..., 3]
    yy, xx = np.where(a > 0)
    box = (xx.min(), yy.min(), xx.max() + 1, yy.max() + 1)
    img = img.crop(box)
    p = int(max(img.size) * pad)
    canvas = Image.new("RGBA", (img.width + 2 * p, img.height + 2 * p), (0, 0, 0, 0))
    canvas.paste(img, (p, p))
    return canvas


def resize(img, size):
    """Premultiplied-alpha Lanczos so scaled edges don't pick up dark/light fringes."""
    a = np.array(img.convert("RGBA")).astype(np.float32)
    a[..., :3] *= a[..., 3:] / 255.0
    chans = [Image.fromarray(a[..., i], "F").resize(size, Image.LANCZOS) for i in range(4)]
    r = np.stack([np.array(c) for c in chans], -1)
    al = np.clip(r[..., 3:], 0, 255)
    rgb = np.where(al > 0, r[..., :3] / np.maximum(al, 1e-3) * 255.0, 0)
    return Image.fromarray(np.clip(np.concatenate([rgb, al], -1), 0, 255).astype(np.uint8), "RGBA")


def fit(img, longest):
    s = longest / max(img.size)
    return resize(img, (max(1, round(img.width * s)), max(1, round(img.height * s))))


# ---- 2. full body ----------------------------------------------------------------------------
full = trim(master)
full.save(out / "doesy.png", optimize=True)                         # master, original resolution
for h in (512, 256, 128):
    fit(full, h).save(out / f"doesy-full-{h}.png", optimize=True)

# ---- 3. head (for anything <= ~64px, where the body + sparks turn to mush) ------------------
# Polygon traced on the original cut-out: keeps the ear caps, drops the spark, waving arm and neck.
HEAD_POLY = [(325, 330), (370, 262), (450, 202), (560, 160), (700, 134), (850, 128), (1000, 168), (1100, 258),
             (1150, 360), (1196, 450), (1192, 560), (1132, 642), (1040, 690), (950, 674), (850, 692), (750, 698),
             (650, 697), (550, 689), (470, 667), (400, 627), (345, 562), (322, 450)]
K = 4
m = Image.new("L", (master.width * K, master.height * K), 0)
ImageDraw.Draw(m).polygon([(x * K, y * K) for x, y in HEAD_POLY], fill=255)
m = m.resize(master.size, Image.LANCZOS).filter(ImageFilter.GaussianBlur(0.8))
ha = np.array(master)
ha[..., 3] = np.minimum(ha[..., 3], np.array(m))
head = trim(Image.fromarray(ha), pad=0.02)
head.save(out / "doesy-head.png", optimize=True)

# ---- 4. badges: head on a soft lavender disc / rounded square ---------------------------------
def gradient(size, c1, c2):
    t = np.linspace(0, 1, size)[:, None, None] * np.ones((1, size, 1))
    a, b = np.array(c1, float), np.array(c2, float)
    return Image.fromarray((a + (b - a) * t).astype(np.uint8)).convert("RGBA")


def badge(size, shape="circle", scale=4):
    S = size * scale
    bg = gradient(S, (246, 241, 255), (222, 208, 255))
    mask = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(mask)
    if shape == "circle":
        d.ellipse((0, 0, S - 1, S - 1), fill=255)
    else:
        d.rounded_rectangle((0, 0, S - 1, S - 1), radius=int(S * 0.24), fill=255)
    bg.putalpha(mask)
    inner = fit(head, int(S * (0.80 if shape == "circle" else 0.84)))
    bg.alpha_composite(inner, ((S - inner.width) // 2, int(S * 0.5 - inner.height * 0.5) + int(S * 0.01)))
    return bg.resize((size, size), Image.LANCZOS)


for s in (256, 128, 64):
    badge(s, "circle").save(out / f"doesy-badge-{s}.png", optimize=True)
badge(512, "square").save(out / "icon-512.png", optimize=True)
badge(180, "square").save(out / "apple-touch-icon.png", optimize=True)
for s in (64, 48, 32):
    badge(s, "square").save(out / f"favicon-{s}.png", optimize=True)
badge(256, "square").save(out / "favicon.ico", sizes=[(48, 48), (32, 32), (16, 16)])

# ---- 5. logo lockup (SVG with embedded badge, replaces the teal "+" logo) --------------------------
buf = io.BytesIO()
badge(128, "square").save(buf, "PNG")
b64 = base64.b64encode(buf.getvalue()).decode()
(out.parent / "logo.svg").write_text(
    '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="220" height="44" viewBox="0 0 220 44">\n'
    f'  <image x="0" y="2" width="40" height="40" xlink:href="data:image/png;base64,{b64}" href="data:image/png;base64,{b64}"/>\n'
    '  <text x="50" y="28" font-family="Inter, Segoe UI, Helvetica, Arial, sans-serif" font-size="19" font-weight="700" fill="#0F172A">Pharma AI</text>\n'
    "</svg>\n"
)
print(sorted(p.name for p in out.iterdir()))
