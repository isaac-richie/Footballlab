"""Generate the Football Lab wordmark and banners as font-free SVGs.

The lettering is drawn as strokes (only F, O, T, B, A, L are needed), so the
files look identical everywhere, with no font installed. Run from the repo root:

    python3 tools/make_brand.py

Writes to community/web/brand/. PNG copies are made with macOS Quick Look
(qlmanage) when available, because social sites reject SVG uploads.
"""
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'community' / 'web' / 'brand'
MARK = (ROOT / 'community' / 'web' / 'logo-mark.svg').read_text()

STROKE = 7
# Glyphs on a 40-unit-high grid, drawn as centre-line strokes: (path, advance width).
GLYPHS = {
    'F': ('M3.5 40V3.5H20M3.5 20.5H16', 20),
    'O': ('M11 3.5h0a7.5 7.5 0 0 1 7.5 7.5v18a7.5 7.5 0 0 1-15 0V11A7.5 7.5 0 0 1 11 3.5Z', 22),
    'T': ('M0 3.5H22M11 3.5V40', 22),
    # B is two strokes meeting at the stem; square ends close the corners cleanly.
    'B': ('M3.5 36.5V3.5h9a7.75 7.75 0 0 1 0 15.5h-9M3.5 19h10a8.75 8.75 0 0 1 0 17.5h-10', 26, 'square'),
    'A': ('M3.5 40V11a7.5 7.5 0 0 1 15 0V40M3.5 24h15', 22),
    'L': ('M3.5 0V36.5H20', 20),
}
GAP, SPACE = 5, 14


def lettering(word, colour, x0=0.0):
    """Return (svg group markup, width) for one word."""
    parts, x = [], x0
    for ch in word:
        path, w, *cap = GLYPHS[ch]
        extra = f' stroke-linecap="{cap[0]}"' if cap else ''
        parts.append(f'<path transform="translate({x:.1f} 0)" d="{path}"{extra}/>')
        x += w + GAP
    width = x - GAP - x0
    group = (f'<g fill="none" stroke="{colour}" stroke-width="{STROKE}" stroke-linejoin="round" '
             f'stroke-linecap="butt">{"".join(parts)}</g>')
    return group, width


def mark(prefix):
    """The logo mark's inner content with ids made unique for embedding."""
    inner = re.search(r'<svg[^>]*>(.*)</svg>', MARK, re.S).group(1)
    inner = re.sub(r'<title>.*?</title>', '', inner)
    for name in ('ball', 'rim'):
        inner = inner.replace(f'id="{name}"', f'id="{prefix}-{name}"').replace(f'url(#{name})', f'url(#{prefix}-{name})')
    return inner


def wordmark(text_colour, lab_colour, prefix):
    """Mark + FOOTBALL LAB, slanted for pace. Returns (markup, width, height) in units."""
    foot, wf = lettering('FOOTBALL', text_colour)
    lab, wl = lettering('LAB', lab_colour, wf + SPACE)
    words_w = wf + SPACE + wl
    scale = 1.25                      # letters 50 units tall next to a 64-unit mark
    mark_size, pad = 64, 18
    width = mark_size + pad + words_w * scale + 14
    markup = (f'<svg x="0" y="0" width="{mark_size}" height="{mark_size}" viewBox="0 0 64 64">{mark(prefix)}</svg>'
              f'<g transform="translate({mark_size + pad + 7} 7) scale({scale}) skewX(-9)">{foot}{lab}</g>')
    return markup, width, mark_size


def lab_gradient(prefix):
    return (f'<linearGradient id="{prefix}-lab" x1="0" y1="0" x2="1" y2="0">'
            f'<stop offset="0" stop-color="#d9ff8a"/><stop offset="1" stop-color="#8fcf2f"/></linearGradient>')


def write_wordmark(name, text_colour):
    body, w, h = wordmark(text_colour, 'url(#wm-lab)', 'wm')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.0f} {h}" width="{w * 4:.0f}" height="{h * 4}" '
           f'role="img" aria-label="Football Lab"><title>Football Lab</title><defs>{lab_gradient("wm")}</defs>{body}</svg>')
    (OUT / name).write_text(svg)


def banner(name, W, H, tagline=True):
    body, w, h = wordmark('#f4f7fb', 'url(#bn-lab)', 'bn')
    scale = min(W * 0.62 / w, H * 0.34 / h)
    x, y = (W - w * scale) / 2, H * (0.36 if tagline else 0.5) - h * scale / 2
    lines = ''.join(f'<line x1="{W * f}" y1="0" x2="{W * f}" y2="{H}"/>' for f in (0.5,))
    pitch = (f'<g fill="none" stroke="#ffffff" stroke-opacity=".07" stroke-width="2">'
             f'<rect x="{W * .04}" y="{H * .08}" width="{W * .92}" height="{H * .84}" rx="4"/>{lines}'
             f'<circle cx="{W / 2}" cy="{H / 2}" r="{H * .2}"/>'
             f'<rect x="{W * .04}" y="{H * .28}" width="{W * .1}" height="{H * .44}"/>'
             f'<rect x="{W * .86}" y="{H * .28}" width="{W * .1}" height="{H * .44}"/></g>')
    tag = ''
    if tagline:
        tag = (f'<text x="{W / 2}" y="{H * .74}" text-anchor="middle" fill="#c9d3df" font-size="{H * .075:.0f}" '
               f'font-family="HelveticaNeue-CondensedBold, \'Barlow Condensed\', \'Arial Narrow\', Arial, sans-serif" '
               f'font-weight="700" letter-spacing="{H * .012:.1f}">READ THE GAME. FIND THE NUMBERS.</text>'
               f'<rect x="{W / 2 - H * .09}" y="{H * .8}" width="{H * .18}" height="{H * .012}" rx="2" fill="url(#bn-lab)"/>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="Football Lab">'
           f'<defs>{lab_gradient("bn")}'
           f'<radialGradient id="bn-g1" cx=".15" cy=".1" r=".7"><stop offset="0" stop-color="#c2f25e" stop-opacity=".28"/><stop offset="1" stop-color="#c2f25e" stop-opacity="0"/></radialGradient>'
           f'<radialGradient id="bn-g2" cx=".9" cy=".9" r=".7"><stop offset="0" stop-color="#74bdfc" stop-opacity=".24"/><stop offset="1" stop-color="#74bdfc" stop-opacity="0"/></radialGradient>'
           f'<radialGradient id="bn-g3" cx=".6" cy=".2" r=".6"><stop offset="0" stop-color="#a07bff" stop-opacity=".16"/><stop offset="1" stop-color="#a07bff" stop-opacity="0"/></radialGradient></defs>'
           f'<rect width="{W}" height="{H}" fill="#0a0d12"/><rect width="{W}" height="{H}" fill="url(#bn-g1)"/>'
           f'<rect width="{W}" height="{H}" fill="url(#bn-g2)"/><rect width="{W}" height="{H}" fill="url(#bn-g3)"/>{pitch}'
           f'<g transform="translate({x:.1f} {y:.1f}) scale({scale:.4f})">{body}</g>{tag}</svg>')
    (OUT / name).write_text(svg)


CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'


def to_png(name, size, scale=1):
    """Exact-size PNG via headless Chrome (falls back to Quick Look, which may crop)."""
    src, dst = OUT / name, OUT / name.replace('.svg', '.png')
    # Render at the size the file declares (wordmarks declare 4x their drawing area).
    w, h = (int(float(v)) for v in re.search(r' width="([\d.]+)" height="([\d.]+)"', src.read_text()).groups())
    if Path(CHROME).exists():
        subprocess.run([CHROME, '--headless=new', '--disable-gpu', '--hide-scrollbars', '--default-background-color=00000000', f'--force-device-scale-factor={scale}',
                        f'--window-size={w},{h}', f'--screenshot={dst}', src.as_uri()], capture_output=True, timeout=90)
        return dst.exists()
    if shutil.which('qlmanage'):
        subprocess.run(['qlmanage', '-t', '-s', str(size), '-o', str(OUT), str(src)], capture_output=True, timeout=60)
        made = OUT / (name + '.png')
        if made.exists():
            made.rename(dst)
            return True
    return False


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    write_wordmark('wordmark.svg', '#f4f7fb')            # for dark backgrounds
    write_wordmark('wordmark-on-light.svg', '#0b0f14')   # for light backgrounds
    banner('banner-x-1500x500.svg', 1500, 500)
    banner('share-1200x630.svg', 1200, 630)
    for n, s in (('banner-x-1500x500.svg', 1500), ('share-1200x630.svg', 1200), ('wordmark.svg', 0), ('wordmark-on-light.svg', 0)):
        print(n, 'png' if to_png(n, s) else 'svg only')
    print('written to', OUT)
