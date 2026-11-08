"""Adaptives Android-Icon aus store/play_icon_512.png.

Hintergrund: Innenfeld des Logos (Raster + Leuchten) ohne Schrift, randlos auf 108 dp.
Vordergrund: Schriftzug mit Kontur/Glanz, so skaliert, dass er im sicheren 66-dp-Kreis liegt.
"""
import sys
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw

root = Path(sys.argv[1]); out = Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
src = np.array(Image.open(root / 'store/play_icon_512.png').convert('RGB'))
x0, x1 = 44, 468                                   # Innenfeld innerhalb des Leuchtrahmens
inner = src[x0:x1, x0:x1].copy()
hsv = cv2.cvtColor(inner, cv2.COLOR_RGB2HSV)
lum = inner.mean(2)
# Schrift: hell (Weiß/Hellblau/Gelb) – plus Kontur und Schein durch Ausdehnen
core = ((lum > 120) & ((hsv[..., 1] < 140) | (inner[..., 0] > 120))).astype(np.uint8)
core = cv2.morphologyEx(core, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
n, lab, stats, _ = cv2.connectedComponentsWithStats(core)
keep = np.zeros_like(core)
for i in range(1, n):
    if stats[i, cv2.CC_STAT_AREA] > 40: keep[lab == i] = 1
text = cv2.dilate(keep, np.ones((3, 3), np.uint8), iterations=6)          # dunkle Kontur
ys, xs = np.nonzero(text)
print('Schrift-Bereich', xs.min() + x0, xs.max() + x0, ys.min() + x0, ys.max() + x0)
bgimg = cv2.inpaint(inner, cv2.dilate(text, np.ones((3, 3), np.uint8), iterations=3) * 255, 9, cv2.INPAINT_TELEA)
bgimg = cv2.GaussianBlur(bgimg, (0, 0), 2.5)
alpha = cv2.GaussianBlur(text.astype(np.float32), (0, 0), 2.2)
alpha = np.clip(alpha * 1.4, 0, 1)

S = 432; DP = S / 108
cy, cx = (ys.min() + ys.max()) / 2, (xs.min() + xs.max()) / 2
corner = np.hypot(xs - cx, ys - cy).max()
scale = 31.5 * DP / corner                     # weiteste Schriftstelle auf 31,5 dp vom Mittelpunkt
# Hintergrund: Innenfeld so groß, dass die sichtbaren 72 dp (inkl. Parallax-Rand) gefüllt sind
# Sauberer Hintergrund im Stil des Logos: blaues Leuchten zur Mitte, dunkler Rand, feines Raster
yy, xx = np.mgrid[0:S, 0:S].astype(np.float32)
d = np.hypot((xx - S / 2) / (S / 2), (yy - S * .46) / (S / 2))
t = np.clip(d / 0.95, 0, 1) ** 1.3
centre, edge = np.array([10, 98, 205], np.float32), np.array([2, 20, 52], np.float32)
bgarr = centre * (1 - t[..., None]) + edge * t[..., None]
step = 9 * DP
for g in (np.abs(((xx - S / 2) / step) - np.round((xx - S / 2) / step)) * step,
          np.abs(((yy - S / 2) / step) - np.round((yy - S / 2) / step)) * step):
    line = np.clip(1.2 - g, 0, 1)[..., None] * (0.22 * (1 - t[..., None] * .6))
    bgarr = bgarr * (1 - line) + np.array([60, 170, 255], np.float32) * line
background = Image.fromarray(np.clip(bgarr, 0, 255).astype(np.uint8))
fg_rgba = np.dstack([inner, (alpha * 255).astype(np.uint8)])
size = round(inner.shape[0] * scale)
fg = Image.fromarray(fg_rgba, 'RGBA').resize((size, size), Image.LANCZOS)
foreground = Image.new('RGBA', (S, S), (0, 0, 0, 0))
ox = round(S / 2 - cx * scale); oy = round(S / 2 - cy * scale)
foreground.alpha_composite(fg, (ox, oy)) if ox >= 0 and oy >= 0 else foreground.paste(fg, (ox, oy), fg)

full = background.convert('RGBA'); full.alpha_composite(foreground)
dens = {'mdpi': 1, 'hdpi': 1.5, 'xhdpi': 2, 'xxhdpi': 3, 'xxxhdpi': 4}
for d, f in dens.items():
    folder = out / f'mipmap-{d}'; folder.mkdir(exist_ok=True)
    s = round(108 * f)
    background.resize((s, s), Image.LANCZOS).save(folder / 'ic_launcher_background.png')
    foreground.resize((s, s), Image.LANCZOS).save(folder / 'ic_launcher_foreground.png')
    v = round(18 * DP); legacy = full.crop((v, v, S - v, S - v))
    L = round(48 * f); big = legacy.resize((L * 4, L * 4), Image.LANCZOS)
    m = Image.new('L', big.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, L * 4 - 1, L * 4 - 1), radius=L * 4 // 5, fill=255)
    big.putalpha(m); big.resize((L, L), Image.LANCZOS).save(folder / 'ic_launcher.png')
# Play-Store-Icon 512 (randlos, Google rundet selbst ab)
v = round(18 * DP); full.crop((v, v, S - v, S - v)).resize((512, 512), Image.LANCZOS).convert('RGB').save(out / 'play_icon_512.png')
prev = Image.new('RGBA', (3 * 440, 440), (240, 240, 240, 255))
vis = full.crop((v, v, S - v, S - v)).resize((400, 400), Image.LANCZOS)
for i, r in enumerate([200, 140, 48]):
    m = Image.new('L', (400, 400), 0); ImageDraw.Draw(m).rounded_rectangle((0, 0, 399, 399), radius=r, fill=255)
    t = vis.copy(); t.putalpha(m); prev.alpha_composite(t, (20 + i * 440, 20))
prev.save(out / 'preview.png')
