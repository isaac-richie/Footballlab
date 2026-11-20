"""Gather one component's CSS from every layer of index.html into a single block.

Every rule whose selectors all belong to the component (match TOKEN) is removed from where it is
and re-emitted, merged, in one block at the end of the stylesheet:

  * rules with the same selector in the same @media context are merged; for each property the value
    that wins today is kept (a later value of equal or higher importance replaces an earlier one)
  * the merged rules keep the order of their last appearance, grouped by @media context in the order
    the contexts first appear, so overrides inside the component still resolve the same way

Rules shared with other components (a selector list mixing this component with others) are left
where they are. Moving the block later can only change a result where an unrelated rule of equal
specificity sat between the old copies and used to win: check with computed-style snapshots.

    python3 tools/css_component.py vip '\\.(vlx?|vl-[\\w-]+)(?![\\w-])'          # report
    python3 tools/css_component.py vip '...' --write
"""
import re
import sys
from collections import OrderedDict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import css_cleanup as C  # noqa: E402

FILE = C.FILE


def specificity(sel):
    """(ids, classes/attributes/pseudo-classes, elements) for one simple selector chain."""
    s = re.sub(r'::?(before|after|first-line|first-letter|placeholder|selection|marker)\b', ' E ', sel)
    s = re.sub(r':not\(([^)]*)\)', r' \1 ', s)
    ids = len(re.findall(r'#[\w-]+', s))
    cls = len(re.findall(r'\.[\w-]+|\[[^\]]*\]|:(?!:)[\w-]+(\([^)]*\))?', s))
    els = len(re.findall(r'(?:^|[\s>+~(])([a-zA-Z][\w-]*|E)(?=[.#:\[\s>+~)]|$)', s))
    return (ids, cls, els)


def normaliser(aliases):
    """Map selector forms that name the same element onto one key: aliases are the class chains that
    always appear together on the component's root (e.g. '.vl.vlx', '.vlx', '.vl')."""
    alts = sorted(aliases, key=len, reverse=True)
    root = re.compile('(?<![\\w-])(' + '|'.join(re.escape(a) for a in alts) + ')(?![\\w-])')

    def norm(sel):
        sel = re.sub(r'\s+', ' ', sel.strip())
        parts = sel.split(' ')
        # the root as an ancestor of a part is implied (parts only appear inside the root): drop it
        if len(parts) > 1 and root.fullmatch(parts[0]):
            sel = ' '.join(parts[1:])
        return root.sub('ROOT', sel)
    return norm


def gather(html, name, token, aliases=None, emit_root=None):
    tok = re.compile(token)
    a, b = html.index('<style>') + len('<style>'), html.index('</style>')
    css = html[a:b]
    rules = list(C.walk(css))
    mine = [r for r in rules if all(tok.search(s) for s in r[1].split(',') if s.strip())]
    norm = normaliser(aliases) if aliases else (lambda sel: re.sub(r'\s+', ' ', sel.strip()))
    merged = OrderedDict()                     # context -> OrderedDict(target -> {prop: (value, important, spec, idx)})
    order = OrderedDict()                      # (context, target) -> index of last appearance
    spec_of = {}                               # (context, target) -> highest specificity among its selectors
    text_of = {}                               # (context, target) -> the selector text that had it
    split = []
    for i, (ctx, sel, body, s, e) in enumerate(mine):
        for one in (x for x in sel.split(',') if x.strip()):
            split.append((i, ctx, one.strip(), body))
    for i, ctx, one, body in split:
        key = norm(one)
        sp = specificity(one)
        block = merged.setdefault(ctx, OrderedDict()).setdefault(key, OrderedDict())
        for prop, val, imp in C.decls(body):
            old = block.get(prop)
            # the browser's rule: importance first, then specificity, then the later rule
            if old is None or (imp, sp, i) >= (old[1], old[2], old[3]):
                block.pop(prop, None)
                block[prop] = (val, imp, sp, i)
        order[(ctx, key)] = i
        if sp >= spec_of.get((ctx, key), (0, 0, 0)):
            spec_of[(ctx, key)] = sp
            text_of[(ctx, key)] = re.sub(r'\s+', ' ', one)
    # 2. Values that a rule OUTSIDE the component already beats today (a shared selector list naming the
    #    component, later in the file with >= importance and specificity) are dropped: moving the block
    #    to the end must not let them win.
    pos = {id(r): k for k, r in enumerate(rules)}
    mine_ids = {id(r) for r in mine}
    first_idx = {}
    for i, (ctx, sel, body, s, e) in enumerate(mine):
        first_idx.setdefault(i, pos[id(mine[i])])
    for r in rules:
        if id(r) in mine_ids:
            continue
        rctx, rsel, rbody, rs, re_ = r
        for one in (x for x in rsel.split(',') if x.strip()):
            if not tok.search(one):
                continue
            key = norm(one)
            block = merged.get(rctx, {}).get(key)
            if not block:
                continue
            osp = specificity(one)
            for prop, val, imp in C.decls(rbody):
                cur = block.get(prop)
                if cur is None:
                    continue
                cur_val, cur_imp, cur_sp, cur_i = cur
                if (imp, osp, pos[id(r)]) > (cur_imp, cur_sp, first_idx[cur_i]):
                    del block[prop]
    out = [f'\n/* ================= Component: {name} (all of its rules, gathered from every layer) ================= */']
    for ctx, sels in merged.items():
        lines = []
        for sel in sorted(sels, key=lambda k: order[(ctx, k)]):
            props = sels[sel]
            if not props:
                continue
            out_sel = text_of.get((ctx, sel), sel)
            body = ';'.join(f'{p}:{v}' for p, (v, *_) in props.items())
            # neighbours with the same declarations become one selector list again (order is unchanged)
            if lines and lines[-1][1] == body:
                lines[-1] = (lines[-1][0] + ',' + out_sel, body)
            else:
                lines.append((out_sel, body))
        lines = [f'{s}{{{b}}}' for s, b in lines]
        if not lines:
            continue
        if ctx:
            out.append(''.join(f'{c}{{' for c in ctx) + '\n  ' + '\n  '.join(lines) + '\n' + '}' * len(ctx))
        else:
            out.extend(lines)
    block = '\n'.join(out) + '\n'
    new_css = css
    for r in sorted(mine, key=lambda r: -r[3]):
        new_css = new_css[:r[3]] + new_css[r[4]:]
    new_css = re.sub(r'@media[^{]*\{\s*\}', '', new_css)
    new_css = re.sub(r'\n\s*\n\s*\n+', '\n\n', new_css)
    stats = dict(rules_before=len(mine), rules_after=sum(len(v) for v in merged.values()),
                 important_before=sum(r[2].count('!important') for r in mine), important_after=block.count('!important'))
    return html[:a] + new_css + block + html[b:], block, stats


if __name__ == '__main__':
    name, token = sys.argv[1], sys.argv[2]
    aliases = [a for a in (sys.argv[3].split('|') if len(sys.argv) > 3 and not sys.argv[3].startswith('--') else [])]
    html = FILE.read_text()
    new, block, stats = gather(html, name, token, aliases or None, aliases[0] if aliases else None)
    print(stats)
    if '--write' in sys.argv:
        FILE.write_text(new)
        print('written')
    else:
        print(block[:3000])
