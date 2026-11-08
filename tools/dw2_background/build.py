"""Baut die Ebenen des DW2-Menühintergrunds in Spielauflösung (1 Pixel = 1 PS1-Pixel).

Messwerte aus dem Referenz-Screenshot (1536×1152 = 320×240 × 4,8) und dem Statusbildschirm-Video:
  Raster: senkrecht stark x≡0, schwach x≡16 (mod 32); waagerecht stark y≡8, schwach y≡0,16 (mod 32)
  Schattenlinien (statisch): x≡4, y≡12 (mod 32)
  Zeichenzeilen: B bei y=103–133 (Wort ab x=20), A 57 px höher (Wort ab x=238), Streifen 579 px
  Bewegung: nach links, 1 Pixel je VBlank (60 Hz) – aus dem Video, siehe Doku
"""
import sys, json
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0, str(Path(__file__).parent))
import glyphs

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else 'out'); OUT.mkdir(exist_ok=True)
rng = np.random.default_rng(1999)

def ps1(c):   # auf 15-Bit-Farbe (5 Bit je Kanal) runden wie die PS1
    return (np.round(np.asarray(c, float) / 8) * 8).clip(0, 248)

# ---------------- Ebene 1: Grund (statisch)
H, W = 240, 320
base = np.zeros((H, W, 3))
dark_top, band, dark_bot = np.array([0, 1, 58]), np.array([1, 21, 89]), np.array([0, 1, 56])
for y in range(H):
    base[y] = band if 42 <= y <= 170 else (dark_top if y < 42 else dark_bot)
# wolkige Struktur wie im Original (weich, geringe Amplitude)
noise = rng.normal(0, 1, (H // 4 + 2, W // 4 + 2))
from PIL import ImageFilter
n_img = Image.fromarray(((noise - noise.min()) / np.ptp(noise) * 255).astype(np.uint8)).resize((W + 8, H + 8), Image.BICUBIC)
n = (np.array(n_img.filter(ImageFilter.GaussianBlur(2.2)), float)[4:4 + H, 4:4 + W] / 255 - .5)
n2 = rng.normal(0, 1, (H, W)) * .25
amp = np.where((np.arange(H) >= 42) & (np.arange(H) <= 170), 1.0, .6)[:, None]
base[..., 1] += (n * 22 + n2 * 3) * amp
base[..., 2] += (n * 16 + n2 * 3) * amp
# Schattenlinien des Rasters
for x in range(4, W, 32): base[:, x] *= .55
for y in range(12, H, 32): base[y] *= .55
Image.fromarray(ps1(base).astype(np.uint8)).save(OUT / 'bg_base.png')

# ---------------- Ebene 2: Zeichenstreifen (bewegt), Länge 579 px
L = 579
WORD_U = (0, 216)            # zwei Worte im Streifen (Abstände 29 bzw. 173 px)
ROWS = [('A', 46 - 103, 238), ('B', 0, 20), ('C', 186 - 103, 128)]   # (Name, y-Versatz, x des 1. Wortes)
GLYPH = (32, 168, 224, 200)   # helles Blau, ~78 % deckend
DIRS = {'A': 'l', 'B': 'r', 'C': 'l'}   # wie im Original: Zeilen abwechselnd nach links / rechts
strips = {d: np.zeros((H, L, 4), np.uint8) for d in 'lr'}
for name, dy, x0 in ROWS:
    strip = strips[DIRS[name]]
    for wu in WORD_U:
        for g, ox in glyphs.WORD:
            for y, s_ in g.items():
                yy = y + dy
                if not 0 <= yy < H: continue
                for x, ch in enumerate(s_):
                    if ch == '#': strip[yy, (x0 + wu + ox + x) % L] = GLYPH
for d, strip in strips.items():
    Image.fromarray(strip, 'RGBA').save(OUT / f'bg_glyphs_{d}.png')

# ---------------- Ebene 3: Raster (statisch), Kachel 32×32
grid = np.zeros((32, 32, 4), np.uint8)
THICK, THIN = (32, 168, 144, 255), (24, 104, 128, 255)
grid[0, :] = THIN; grid[16, :] = THIN; grid[8, :] = THICK
grid[:, 16] = np.where(grid[:, 16, 3:4] > 0, grid[:, 16], THIN)
grid[:, 16] = [THICK if y == 8 else THIN for y in range(32)]
grid[:, 0] = THICK
Image.fromarray(grid, 'RGBA').save(OUT / 'bg_grid.png')

# ---------------- Rahmen (9-Slice, Pixelkunst nach den Menüfenstern)
P = {'.': (0, 0, 0, 0), 'K': (64, 64, 72, 255), 'D': (112, 112, 120, 255), 'M': (152, 152, 160, 255),
     'L': (200, 204, 212, 255), 'W': (240, 248, 248, 255)}
TL = ["KKKKKKKKKK",
      "KWWWWWLDKK",
      "KWLLLLDKMM",
      "KWLLLD....",
      "KWLLD.....",
      "KWLD......",
      "KLLD......",
      "KLLD......",
      "KLLD......",
      "KLLD......"]
C = 10
nine = np.zeros((2 * C + 1, 2 * C + 1, 4), np.uint8)
def put(rows, ox, oy, fx=False, fy=False):
    for y, r in enumerate(rows):
        for x, ch in enumerate(r):
            X = C - 1 - x if fx else x; Y = C - 1 - y if fy else y
            nine[oy + Y, ox + X] = P[ch]
put(TL, 0, 0); put(TL, C + 1, 0, fx=True); put(TL, 0, C + 1, fy=True); put(TL, C + 1, C + 1, fx=True, fy=True)
top = "KKW"; left = "KLLD"
for i, ch in enumerate(top):
    nine[i, C] = P[ch]; nine[2 * C - i, C] = P[ch]
for i, ch in enumerate(left):
    nine[C, i] = P[ch]; nine[C, 2 * C - i] = P[ch]
# Endstücke der weißen Kante: kurzes graues Segment wie im Original
Image.fromarray(nine, 'RGBA').save(OUT / 'frame9.png')
# Seitenlasche (Mitte links/rechts)
TAB = ["KKKKK",
       "KLLLK",
       "KDDDK",
       "KLLLK",
       "KDDDK",
       "KLLLK",
       "KDDDK",
       "KLLLK",
       "KKKKK"]
Image.fromarray(np.array([[P[c] for c in r] for r in TAB], np.uint8), 'RGBA').save(OUT / 'frame_tab.png')

# ---------------- Vergleichsbild t=0 (320×240) wie im Screenshot
def compose(t=0):
    img = Image.fromarray(ps1(base).astype(np.uint8)).convert('RGBA')
    for d, strip in strips.items():
        sh = np.roll(strip, -t if d == 'l' else t, axis=1)[:, :W]
        img.alpha_composite(Image.fromarray(np.ascontiguousarray(sh), 'RGBA'))
    gt = Image.new('RGBA', (W, H))
    g = Image.fromarray(grid, 'RGBA')
    for yy in range(0, H, 32):
        for xx in range(0, W, 32): gt.alpha_composite(g, (xx, yy))
    img.alpha_composite(gt)
    return img
compose().save(OUT / 'recon_t0.png')
json.dump({'strip_length': L, 'tile_h': H, 'speed_px_per_vblank': 1}, open(OUT / 'meta.json', 'w'))
print('ok')
