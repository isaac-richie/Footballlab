"""Find and remove dead CSS in index.html's stylesheet, safely.

Two kinds of dead code are removed, both provable without running the page:

  dead rules         a selector list in which every selector names a class or id that appears nowhere
                     else in index.html (no markup, no script string), so it can never match
  overridden values  a property in a rule when a LATER rule with the identical selector, in the same
                     @media context, sets the same property with equal or higher importance: for every
                     element either rule matches, the later one always wins

Usage:
    python3 tools/css_cleanup.py            # report only
    python3 tools/css_cleanup.py --write    # rewrite index.html
"""
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILE = ROOT / 'index.html'


def split_top(text):
    """Split a CSS block into top-level items: (kind, prelude, body, start, end)."""
    items, i, n = [], 0, len(text)
    while i < n:
        if text.startswith('/*', i):
            j = text.find('*/', i + 2)
            i = n if j < 0 else j + 2
            continue
        if text[i].isspace():
            i += 1
            continue
        start = i
        depth, j, quote = 0, i, None
        while j < n:
            c = text[j]
            if quote:
                if c == '\\':
                    j += 2
                    continue
                if c == quote:
                    quote = None
            elif c in '"\'':
                quote = c
            elif text.startswith('/*', j):
                k = text.find('*/', j + 2)
                j = n if k < 0 else k + 2
                continue
            elif c == '{':
                if depth == 0:
                    brace = j
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    j += 1
                    break
            elif c == ';' and depth == 0:          # @import / @charset style statement
                j += 1
                brace = None
                break
            j += 1
        chunk = text[start:j]
        if '{' in chunk and chunk.rstrip().endswith('}'):
            b = chunk.index('{')
            items.append(('at' if chunk.lstrip().startswith('@') else 'rule', chunk[:b].strip(), chunk[b + 1:chunk.rstrip().rfind('}')], start, j))
        else:
            items.append(('stmt', chunk.strip(), '', start, j))
        i = j
    return items


def decls(body):
    """[(prop, value, important)] from a declaration block (keeps order)."""
    out, buf, depth, quote = [], '', 0, None
    for c in body + ';':
        if quote:
            buf += c
            if c == quote:
                quote = None
            continue
        if c in '"\'':
            quote = c
        elif c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
        if c == ';' and depth == 0:
            d = buf.strip()
            buf = ''
            if not d or ':' not in d:
                continue
            prop, val = d.split(':', 1)
            val = val.strip()
            imp = bool(re.search(r'!\s*important\s*$', val))
            out.append((prop.strip().lower(), val, imp))
            continue
        buf += c
    return out


def walk(text, context=()):
    """Yield (context, selector, body, start, end) for every style rule, with absolute offsets."""
    for kind, pre, body, s, e in split_top(text):
        if kind == 'rule':
            yield context, pre, body, s, e
        elif kind == 'at' and re.match(r'@(media|supports)\b', pre):
            inner_start = s + text[s:e].index('{') + 1
            for c, sel, b, s2, e2 in walk(body, context + (re.sub(r'\s+', ' ', pre),)):
                yield c, sel, b, inner_start + s2, inner_start + e2


TOKEN = re.compile(r'([.#])(-?[_a-zA-Z][\w-]*)')


DYNAMIC = re.compile(r"""(\$\{|['"`]\s*\+)""")


def alive(name, source):
    """A class or id is alive if it appears whole in markup or scripts, or if a prefix of it is
    followed by code that builds the rest (`tk-${status}`, 'is-' + state ...)."""
    if re.search(r'(?<![\w-])' + re.escape(name) + r'(?![\w-])', source):
        return True
    parts = name.split('-')
    for k in range(1, len(parts) + 1):
        prefix = '-'.join(parts[:k]) + ('-' if k < len(parts) else '')
        for m in re.finditer(r'(?<![\w-])' + re.escape(prefix), source):
            if DYNAMIC.match(source, m.end()):
                return True
    return False


def dead_selector(sel, source):
    names = TOKEN.findall(re.sub(r'\[[^\]]*\]|::?[\w-]+(\([^)]*\))?', ' ', sel))
    return any(not alive(n, source) for _, n in names)


def analyse(html):
    a, b = html.index('<style>') + len('<style>'), html.index('</style>')
    css = html[a:b]
    source = html[:a] + html[b:]                       # markup and scripts: where classes are used
    for extra in sorted((ROOT / 'community' / 'web').glob('*.js')) + [ROOT / 'pwa' / 'sw.js']:
        try:
            source += extra.read_text()                # fx.js, motion.js, kits.js add classes too
        except OSError:
            pass
    rules = list(walk(css))
    dead = [r for r in rules if all(dead_selector(s.strip(), source) for s in r[1].split(',') if s.strip())]
    dead_spans = {(r[3], r[4]) for r in dead}
    # overridden declarations: same context + identical selector text later sets the prop with >= importance
    norm = lambda sel: ','.join(sorted(re.sub(r'\s+', ' ', p.strip()) for p in sel.split(',')))
    later = defaultdict(list)
    for idx, (ctx, sel, body, s, e) in enumerate(rules):
        later[(ctx, norm(sel))].append(idx)
    drop = defaultdict(set)                           # rule index -> props to drop
    for key, idxs in later.items():
        for pos, i in enumerate(idxs):
            if (rules[i][3], rules[i][4]) in dead_spans:
                continue
            mine = decls(rules[i][2])
            for prop, val, imp in mine:
                for j in idxs[pos + 1:]:
                    if any(p == prop and (ip or not imp) for p, _, ip in decls(rules[j][2])):
                        drop[i].add((prop, val, imp))
                        break
            # a property repeated inside one rule: only the last (of >= importance) counts
            for k, (prop, val, imp) in enumerate(mine):
                if any(p == prop and (ip or not imp) for p, _, ip in mine[k + 1:]):
                    drop[i].add((prop, val, imp))
    return css, a, rules, dead, drop


def rewrite(html):
    css, a, rules, dead, drop = analyse(html)
    edits = []                                        # (start, end, replacement) in css offsets
    for r in dead:
        edits.append((r[3], r[4], ''))
    dead_spans = {(r[3], r[4]) for r in dead}
    for i, gone in drop.items():
        ctx, sel, body, s, e = rules[i]
        if (s, e) in dead_spans:
            continue
        keep = []
        for prop, val, imp in decls(body):
            if (prop, val, imp) in gone:
                gone = gone - {(prop, val, imp)}
                continue
            keep.append(f'{prop}:{val}')
        edits.append((s, e, '' if not keep else f'{sel}{{{";".join(keep)}}}'))
    for s, e, rep in sorted(edits, key=lambda x: -x[0]):
        css = css[:s] + rep + css[e:]
    # tidy blank lines and media blocks left empty
    css = re.sub(r'@media[^{]*\{\s*\}', '', css)
    css = re.sub(r'\n\s*\n\s*\n+', '\n\n', css)
    return html[:a] + css + html[html.index('</style>'):], len(dead), sum(len(v) for v in drop.values())


if __name__ == '__main__':
    html = FILE.read_text()
    css, a, rules, dead, drop = analyse(html)
    print(f'{len(css.splitlines())} lines, {len(css):,} chars, {len(rules)} rules, {css.count("!important")} !important')
    print(f'dead rules: {len(dead)}  overridden declarations: {sum(len(v) for v in drop.values())}')
    for r in dead[:25]:
        print('  dead:', r[1][:90].replace('\n', ' '))
    if '--write' in sys.argv:
        new, nd, no = rewrite(html)
        FILE.write_text(new)
        css2 = new[new.index('<style>'):new.index('</style>')]
        print(f'written: {len(css2):,} chars ({len(css) - len(css2):,} fewer), {css2.count("!important")} !important')
