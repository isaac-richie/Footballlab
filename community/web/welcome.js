/* Fairline welcome: "the model at work", a short film drawn live on a canvas (about 4.2 s).
   A tactics board seen from above. The pitch draws itself out from the centre spot; 22 players take
   their places and the ball starts moving; the model reads the game: lime heat where chances come,
   expected-goal tags on the shots, its numbers on the left and the likeliest scores on the right.
   Then the halfway line becomes the result bar and counts up (home 66, draw 21, away 13), thins into
   one lime line that runs out to the edges, and the centre circle settles on it and fills to the line:
   the Fairline mark. The name tracks in under a light sweep, then the circle opens like an iris onto
   the app. Once per visit; a tap, Skip, Esc or Enter jumps to the iris. Off for prefers-reduced-motion
   and when the effects toggle is off. fairlineIntro() replays it; fairlineIntro(2.5) holds 2.5 s. */
(function(){
  'use strict';
  const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
  const off = () => { try{ return localStorage.getItem('fx') === 'off' }catch{ return false } };

  const css = document.createElement('style');
  css.textContent = `
  .fl-intro{position:fixed;inset:0;z-index:1000;background:#05070a;overflow:hidden;cursor:pointer;--lime:#c2f25e;
    -webkit-mask-repeat:no-repeat;mask-repeat:no-repeat}
  .fl-intro canvas{position:absolute;inset:0;width:100%;height:100%;display:block}
  .fl-vig{position:absolute;inset:0;z-index:2;pointer-events:none;background:radial-gradient(ellipse 80% 75% at 50% 50%,transparent 45%,rgba(0,0,0,.7) 100%)}
  .fl-grain{position:absolute;inset:-10%;z-index:2;pointer-events:none;opacity:.07;mix-blend-mode:overlay;
    background:repeating-radial-gradient(circle at 17% 31%,#fff 0 .6px,transparent .6px 2.4px),repeating-radial-gradient(circle at 71% 63%,#fff 0 .5px,transparent .5px 3.1px);
    animation:flGrain .18s steps(3) infinite}
  @keyframes flGrain{33%{transform:translate(-2%,1%)}66%{transform:translate(1%,-2%)}}
  .fl-bar{position:absolute;left:0;right:0;height:8vh;background:#000;z-index:4;transition:transform .7s cubic-bezier(.7,0,.2,1)}
  .fl-bar.t{top:0;transform:translateY(-100%)}
  .fl-bar.b{bottom:0;transform:translateY(100%)}
  .fl-intro.bars .fl-bar{transform:none}
  .fl-intro.end .fl-bar{transition-duration:.5s}
  .fl-intro.end .fl-bar.t{transform:translateY(-100%)}
  .fl-intro.end .fl-bar.b{transform:translateY(100%)}
  .fl-skip{position:absolute;right:max(18px,env(safe-area-inset-right));bottom:2.6vh;z-index:5;padding:6px 2px;border:0;background:none;cursor:pointer;
    font:600 11px/1 Inter,system-ui,sans-serif;letter-spacing:3px;text-transform:uppercase;color:#7d8899;opacity:0;transition:opacity .5s .6s,color .2s}
  .fl-skip:hover{color:#e9eef4}
  .fl-intro.bars .fl-skip{opacity:1}
  .fl-intro.end .fl-skip{opacity:0;transition-delay:0s}
  .fl-title{position:absolute;left:0;right:0;z-index:3;display:grid;justify-items:center;gap:14px;pointer-events:none}
  .fl-word{position:relative;display:flex;font:800 clamp(50px,14vw,112px)/.9 'Barlow Condensed','Arial Narrow',sans-serif;text-transform:uppercase;
    color:#eef2f7;letter-spacing:.5em;margin-right:-.5em;transition:letter-spacing 1s cubic-bezier(.16,1,.3,1),margin 1s cubic-bezier(.16,1,.3,1)}
  .fl-word span{display:inline-block;opacity:0;transform:translateY(.28em) scale(1.12);filter:blur(14px);
    transition:opacity .6s ease,transform .9s cubic-bezier(.16,1,.3,1),filter .7s ease;transition-delay:calc(var(--i) * 45ms)}
  .fl-word span.l{color:var(--lime);text-shadow:0 0 34px rgba(194,242,94,.32)}
  .fl-word::after{content:attr(data-t);position:absolute;inset:0;display:flex;letter-spacing:inherit;color:#fff;pointer-events:none;
    -webkit-mask-image:linear-gradient(105deg,transparent 35%,#000 48%,#000 52%,transparent 65%);mask-image:linear-gradient(105deg,transparent 35%,#000 48%,#000 52%,transparent 65%);
    -webkit-mask-size:300% 100%;mask-size:300% 100%;-webkit-mask-position:120% 0;mask-position:120% 0;opacity:0;mix-blend-mode:screen}
  .fl-intro.word .fl-word{letter-spacing:.05em;margin-right:-.05em}
  .fl-intro.word .fl-word span{opacity:1;transform:none;filter:blur(0)}
  .fl-intro.shine .fl-word::after{opacity:.9;animation:flShine 1s cubic-bezier(.4,0,.2,1) forwards}
  @keyframes flShine{from{-webkit-mask-position:120% 0;mask-position:120% 0}to{-webkit-mask-position:-20% 0;mask-position:-20% 0}}
  .fl-tag{font:600 clamp(11px,2.9vw,13px)/1 Inter,system-ui,sans-serif;letter-spacing:.9em;text-transform:uppercase;color:#8a96a8;opacity:0;
    transition:opacity .9s ease .3s,letter-spacing 1.3s cubic-bezier(.16,1,.3,1) .15s}
  .fl-intro.word .fl-tag{opacity:1;letter-spacing:.42em}`;
  document.head.appendChild(css);

  // ---- easing and timeline helpers
  const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
  const lerp = (a, b, t) => a + (b - a) * t;
  const ease = t => t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
  const easeOut = t => 1 - Math.pow(1 - t, 3);
  const easeOutBack = t => { const c = 1.4; return 1 + (c + 1) * Math.pow(t - 1, 3) + c * Math.pow(t - 1, 2) };
  const easeIn = t => t * t * t;
  const seg = (t, a, b) => clamp((t - a) / (b - a));

  // ---- the pitch, top-down, in metres: x across (±34), y along (±52.5); goals top and bottom, so the
  //      halfway line is horizontal and can become the Fairline level line
  const L = 52.5, Wd = 34, CR = 9.15;
  const ln = (x1, y1, x2, y2) => [[x1, y1], [x2, y2]];
  const box = (s, w, d) => [[-w, s * L], [-w, s * (L - d)], [w, s * (L - d)], [w, s * L]];
  // each chalk mark: points, when it starts drawing, how long (s). Drawn out from the centre spot.
  const MARKS = [
    {pts: [[-Wd, -L], [Wd, -L], [Wd, L], [-Wd, L], [-Wd, -L]], at: .32, dur: .75},
    {pts: box(-1, 20.16, 16.5), at: .55, dur: .35}, {pts: box(1, 20.16, 16.5), at: .55, dur: .35},
    {pts: box(-1, 9.16, 5.5), at: .7, dur: .25}, {pts: box(1, 9.16, 5.5), at: .7, dur: .25},
  ];
  // players in a 4-3-3 against a 4-4-2, as fractions of the half-width and half-length (home attack upwards)
  const HOME = [[0, .92], [-.7, .62], [-.25, .66], [.25, .66], [.7, .62], [-.45, .34], [0, .4], [.45, .34], [-.62, .08], [0, .03], [.62, .08]];
  const AWAY = [[0, -.92], [-.7, -.6], [-.25, -.64], [.25, -.64], [.7, -.6], [-.7, -.28], [-.24, -.32], [.24, -.32], [.7, -.28], [-.2, -.06], [.2, -.06]];
  // the ball's journey: indexes into HOME, then a shot at goal
  const PASSES = [6, 7, 10, 9, 8, 'shot'];
  // where the model sees chances: lime heat (x, y fractions, size, when)
  const HEAT = [[.0, -.72, 1, .95], [-.38, -.6, .7, 1.05], [.4, -.62, .65, 1.12], [.08, -.48, .55, 1.2], [-.1, .7, .55, 1.25], [.3, .64, .45, 1.3]];
  const XG = [[.06, -.74, '0.31', 1.05], [-.4, -.58, '0.08', 1.18], [.42, -.6, '0.12', 1.28], [-.12, .68, '0.06', 1.36]];
  const P1X2 = [.66, .21, .13];
  const SCORES = [['2–0', .116], ['1–0', .109], ['2–1', .098], ['1–1', .091], ['3–0', .074]];
  const READ = [['Attack rating', '1.42'], ['Defence rating', '0.88'], ['Expected goals', '2.09 – 0.85'], ['Matches simulated', '10,000']];

  function intro(hold){
    let seen = false; try{ seen = sessionStorage.getItem('ko') === '1'; sessionStorage.setItem('ko', '1') }catch{}
    const asked = /[?&]intro\b/.test(location.search);                 // ?intro always plays it (for demos)
    if(hold == null && !asked && (seen || reduced() || off())) return;
    if(document.querySelector('.fl-intro')) return;

    const el = document.createElement('div');
    el.className = 'fl-intro'; el.setAttribute('aria-hidden', 'true');
    const letters = [...'FAIRLINE'].map((c, i) => `<span${i > 3 ? ' class="l"' : ''} style="--i:${i}">${c}</span>`).join('');
    el.innerHTML = `<canvas></canvas><div class="fl-vig"></div><div class="fl-grain"></div>
      <div class="fl-title"><div class="fl-word" data-t="FAIRLINE">${letters}</div><div class="fl-tag">The fair price on every game</div></div>
      <i class="fl-bar t"></i><i class="fl-bar b"></i><button class="fl-skip" type="button" tabindex="-1">Skip</button>`;
    document.body.appendChild(el);
    const cv = el.querySelector('canvas'), g = cv.getContext('2d'), title = el.querySelector('.fl-title');
    const mono = "600 12px 'JetBrains Mono',ui-monospace,'SF Mono',Menlo,monospace";
    let W = 0, H = 0, dpr = 1, s = 1, R = 60, cy0 = 0, cy1 = 0, wide = false;
    const size = () => {
      dpr = Math.min(devicePixelRatio || 1, 2); W = innerWidth; H = innerHeight;
      cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); g.setTransform(dpr, 0, 0, dpr, 0, 0);
      s = Math.min(W * .86 / (2 * Wd), H * .74 / (2 * L));           // px per metre
      R = clamp(Math.min(W, H) * .15, 52, 96);                       // the mark's radius at the end
      cy0 = H / 2;                                                   // pitch centre while the game plays
      cy1 = H * .5 - Math.min(H * .13, 120);                         // where the mark sits at the end, leaving room for the name
      wide = W > 900 && W - 2 * Wd * s > 520;                        // room for the side readouts
      title.style.top = (cy1 + R + Math.max(26, R * .42)) + 'px';
    };
    size(); addEventListener('resize', size);

    const DUR = 4.15, EXIT = 3.5, lime = '#c2f25e', chalk = '#e9eef4';
    let t0 = performance.now(), exitAt = EXIT, raf = 0, done = false;

    // camera: a slow pull-back while the game plays, then the pitch centre glides to the mark's spot
    let zoom = 1, cx = 0, cy = 0;
    const P = (x, y) => [cx + x * s * zoom, cy + y * s * zoom];
    const path = (pts, frac) => {                                    // a polyline drawn up to frac of its length
      let len = 0; const segs = [];
      for(let i = 1; i < pts.length; i++){ const d = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]); segs.push(d); len += d }
      let left = len * frac; const a = P(...pts[0]); g.moveTo(a[0], a[1]);
      for(let i = 1; i < pts.length && left > 0; i++){
        const k = Math.min(1, left / segs[i - 1]), x = lerp(pts[i - 1][0], pts[i][0], k), y = lerp(pts[i - 1][1], pts[i][1], k), p = P(x, y);
        g.lineTo(p[0], p[1]); left -= segs[i - 1];
      }
    };
    const glowStroke = (col, a, w, glow) => { g.strokeStyle = col; g.globalAlpha = a * .18; g.lineWidth = glow; g.stroke(); g.globalAlpha = a; g.lineWidth = w; g.stroke(); g.globalAlpha = 1 };
    const ballAt = t => {                                            // where the ball is at time t (pitch metres)
      const k = seg(t, .95, 2.05) * (PASSES.length - 1), i = Math.min(PASSES.length - 2, Math.floor(k)), f = ease(k - i);
      const at = j => PASSES[j] === 'shot' ? [3, -L + .5] : [HOME[PASSES[j]][0] * Wd + drift(PASSES[j], t, 0), HOME[PASSES[j]][1] * L + drift(PASSES[j], t, 1)];
      const a = at(i), b = at(i + 1); return [lerp(a[0], b[0], f), lerp(a[1], b[1], f)];
    };
    const drift = (i, t, axis) => Math.sin(t * (1.1 + i * .13) + i * 1.7 + axis * 2.1) * (axis ? 2.4 : 1.6);

    function frame(now){
      const t = typeof hold === 'number' ? hold : (now - t0) / 1000;
      // camera
      const pull = easeOut(seg(t, 0, 2.0)), settle = ease(seg(t, 2.45, 2.95));
      zoom = lerp(1.18, 1, pull); cx = W / 2; cy = lerp(cy0, cy1, settle);
      const game = 1 - ease(seg(t, 1.85, 2.25));                     // the match fades as the numbers take over
      const bar = seg(t, 1.9, 2.35), thin = ease(seg(t, 2.45, 2.75)), fill = seg(t, 2.65, 3.15);

      g.globalCompositeOperation = 'source-over';
      const bg = g.createRadialGradient(W / 2, H / 2, 0, W / 2, H / 2, Math.hypot(W, H) * .6);
      bg.addColorStop(0, '#0b1410'); bg.addColorStop(1, '#030405'); g.fillStyle = bg; g.fillRect(0, 0, W, H);

      // grass: mowing stripes, fading in under the lines
      const grass = easeOut(seg(t, .25, .9)) * game;
      if(grass > 0){
        for(let i = 0; i < 12; i++){
          const y1 = -L + i * (2 * L / 12), a = P(-Wd, y1), b = P(Wd, y1 + 2 * L / 12);
          g.fillStyle = i % 2 ? '#10241a' : '#0c1c13'; g.globalAlpha = grass * .9; g.fillRect(a[0], a[1], b[0] - a[0], b[1] - a[1]);
        }
        g.globalAlpha = 1;
      }

      // a faint grid: the board the model draws on
      if(game > 0){
        g.strokeStyle = 'rgba(194,242,94,.05)'; g.lineWidth = 1; g.globalAlpha = easeOut(seg(t, .4, 1)) * game; g.beginPath();
        for(let x = -Wd; x <= Wd + .1; x += 6.8){ const a = P(x, -L), b = P(x, L); g.moveTo(a[0], a[1]); g.lineTo(b[0], b[1]) }
        for(let y = -L; y <= L + .1; y += 7){ const a = P(-Wd, y), b = P(Wd, y); g.moveTo(a[0], a[1]); g.lineTo(b[0], b[1]) }
        g.stroke(); g.globalAlpha = 1;
      }

      g.globalCompositeOperation = 'lighter'; g.lineCap = 'round'; g.lineJoin = 'round';
      // the model's heat: where chances will come
      for(const [hx, hy, k, at] of HEAT){
        const a = easeOut(seg(t, at, at + .45)) * game * (.75 + .25 * Math.sin(t * 5 + at * 9)); if(a <= 0) continue;
        const p = P(hx * Wd, hy * L), r = k * 15 * s * zoom, gr = g.createRadialGradient(p[0], p[1], 0, p[0], p[1], r);
        gr.addColorStop(0, `rgba(194,242,94,${.34 * a})`); gr.addColorStop(.5, `rgba(194,242,94,${.12 * a})`); gr.addColorStop(1, 'rgba(194,242,94,0)');
        g.fillStyle = gr; g.beginPath(); g.arc(p[0], p[1], r, 0, 7); g.fill();
      }

      // chalk: the centre spot, then the halfway line and centre circle out from it, then the rest
      const spot = easeOutBack(seg(t, .05, .35));
      if(spot > 0){ const p = P(0, 0); g.fillStyle = chalk; g.globalAlpha = clamp(spot) * (1 - seg(t, 2.4, 2.7)); g.beginPath(); g.arc(p[0], p[1], 2.6 * spot, 0, 7); g.fill(); g.globalAlpha = 1 }
      for(const m of MARKS){
        const f = easeOut(seg(t, m.at, m.at + m.dur)); if(f <= 0 || game <= 0) continue;
        g.beginPath(); path(m.pts, f); glowStroke(chalk, .7 * game, 1.4, 5);
      }

      // the centre circle: drawn round from the spot, then it becomes the mark (growing to R)
      const ringDraw = easeOut(seg(t, .18, .7));
      const rr = lerp(CR * s * zoom, R, settle), cp = P(0, 0);
      if(ringDraw > 0){
        g.beginPath(); g.arc(cp[0], cp[1], rr, -Math.PI / 2, -Math.PI / 2 + ringDraw * Math.PI * 2);
        glowStroke(chalk, lerp(.75, 1, settle) * (1 - .75 * easeOut(bar) * (1 - thin)), lerp(1.4, 2.6, settle), lerp(5, 12, settle));
      }

      // players and the ball
      if(game > 0){
        const ppl = easeOut(seg(t, .55, 1.0));
        const dot = (x, y, col, a, r) => { const p = P(x, y); g.fillStyle = col; g.globalAlpha = a * .25; g.beginPath(); g.arc(p[0], p[1], r * 2.6, 0, 7); g.fill(); g.globalAlpha = a; g.beginPath(); g.arc(p[0], p[1], r, 0, 7); g.fill() };
        const r = clamp(s * zoom * 1.05, 2.4, 5.5);
        HOME.forEach(([x, y], i) => { const k = clamp(ppl * 1.6 - i * .05); if(k > 0) dot(x * Wd + drift(i, t, 0), y * L + drift(i, t, 1), chalk, k * game * .95, r * easeOutBack(k)) });
        AWAY.forEach(([x, y], i) => { const k = clamp(ppl * 1.6 - i * .05); if(k > 0) dot(x * Wd + drift(i + 11, t, 0), y * L + drift(i + 11, t, 1), '#6f86a6', k * game * .9, r * easeOutBack(k)) });
        if(t > .95){
          // the ball, with a short trail
          for(let k = 6; k >= 0; k--){ const b = ballAt(t - k * .02); dot(b[0], b[1], lime, (1 - k / 7) * game * (k ? .35 : 1), r * (k ? .55 : .7)) }
        }
        // expected-goal tags where the shots come from
        g.font = mono; g.textAlign = 'left'; g.textBaseline = 'middle';
        for(const [x, y, v, at] of XG){
          const a = easeOut(seg(t, at, at + .3)) * game; if(a <= 0) continue;
          const p = P(x * Wd, y * L), dx = 10 + (1 - a) * 6;
          g.globalAlpha = a; g.fillStyle = 'rgba(10,14,12,.75)'; g.fillRect(p[0] + dx - 4, p[1] - 9, 62, 18);
          g.fillStyle = lime; g.fillText('xG ' + v, p[0] + dx + 2, p[1] + .5); g.globalAlpha = 1;
        }
      }

      // side readouts on wide screens: the model's numbers (left) and the likeliest scores (right)
      g.globalCompositeOperation = 'source-over';
      if(wide && game > 0){
        const lx = W / 2 - Wd * s - 230, rx = W / 2 + Wd * s + 40, top = H / 2 - 92;
        g.textBaseline = 'alphabetic';
        const head = (x, txt, at) => { const a = easeOut(seg(t, at, at + .3)) * game; g.globalAlpha = a; g.fillStyle = lime; g.font = "700 11px Inter,system-ui,sans-serif"; g.fillText(txt, x, top); g.globalAlpha = 1 };
        head(lx, 'THE MODEL  ·  LIVE', .9); head(rx, 'LIKELIEST SCORES', 1.15);
        READ.forEach(([k, v], i) => {
          const a = easeOut(seg(t, 1.0 + i * .12, 1.3 + i * .12)) * game; if(a <= 0) return;
          const y = top + 32 + i * 34; g.globalAlpha = a;
          g.fillStyle = '#8a96a8'; g.font = "500 12px Inter,system-ui,sans-serif"; g.fillText(k, lx, y);
          g.fillStyle = chalk; g.font = mono.replace('12px', '15px'); g.fillText(v, lx, y + 17); g.globalAlpha = 1;
        });
        SCORES.forEach(([sc, p], i) => {
          const a = easeOut(seg(t, 1.2 + i * .1, 1.5 + i * .1)) * game; if(a <= 0) return;
          const y = top + 30 + i * 30; g.globalAlpha = a;
          g.fillStyle = chalk; g.font = mono.replace('12px', '15px'); g.fillText(sc, rx, y);
          g.fillStyle = 'rgba(233,238,244,.12)'; g.fillRect(rx + 50, y - 9, 110, 6);
          g.fillStyle = i ? 'rgba(233,238,244,.55)' : lime; g.fillRect(rx + 50, y - 9, 110 * (p / .12) * easeOut(a), 6);
          g.fillStyle = '#8a96a8'; g.font = mono; g.fillText((p * 100).toFixed(1) + '%', rx + 170, y); g.globalAlpha = 1;
        });
      }

      // the halfway line: drawn out from the spot, then it becomes the result bar, then the level line
      g.globalCompositeOperation = 'lighter';
      const half = easeOut(seg(t, .1, .55));
      if(half > 0){
        const p = P(0, 0), full = Wd * s * zoom;
        if(bar <= 0 || thin >= 1){
          // a chalk line (early) or the lime level line running out to the frame edges (late)
          const lw = thin >= 1 ? lerp(full, W * .5, easeOut(seg(t, 2.75, 3.05))) : full * half;
          const col = thin >= 1 ? lime : chalk;
          const gr = g.createLinearGradient(p[0] - lw, 0, p[0] + lw, 0);
          gr.addColorStop(0, thin >= 1 ? 'rgba(194,242,94,0)' : col); gr.addColorStop(.12, col); gr.addColorStop(.88, col); gr.addColorStop(1, thin >= 1 ? 'rgba(194,242,94,0)' : col);
          g.beginPath(); g.moveTo(p[0] - lw, p[1]); g.lineTo(p[0] + lw, p[1]);
          g.strokeStyle = gr; g.globalAlpha = (thin >= 1 ? .22 : .12); g.lineWidth = thin >= 1 ? 10 : 5; g.stroke();
          g.globalAlpha = thin >= 1 ? 1 : .75 * Math.max(game, .3); g.lineWidth = thin >= 1 ? 2 : 1.4; g.stroke(); g.globalAlpha = 1;
        } else {
          // the result bar: home, draw, away, growing out of the line, the likeliest one in lime
          const h = lerp(lerp(2, 18, easeOut(bar)), 2, thin), wTot = full * 2, x0 = p[0] - full;
          let x = x0; g.globalCompositeOperation = 'source-over';
          P1X2.forEach((v, i) => {
            const w = wTot * v * easeOut(seg(bar, i * .12, .6 + i * .12));
            g.fillStyle = i === 0 ? lime : `rgba(233,238,244,${i === 1 ? .38 : .22})`;
            g.fillRect(x + (i ? 2 : 0), p[1] - h / 2, Math.max(0, w - (i ? 2 : 0)), h); x += wTot * v;
          });
          // the numbers counting up above the bar
          const na = easeOut(seg(bar, .15, .55)) * (1 - thin);
          if(na > 0){
            g.globalAlpha = na; g.textAlign = 'center'; g.textBaseline = 'alphabetic';
            let xx = x0;
            ['HOME', 'DRAW', 'AWAY'].forEach((lab, i) => {
              const mid = xx + wTot * P1X2[i] / 2, n = Math.round(P1X2[i] * 100 * easeOut(seg(bar, .1, .75)));
              g.fillStyle = i ? 'rgba(233,238,244,.8)' : lime; g.font = `800 ${i ? 26 : 40}px 'Barlow Condensed','Arial Narrow',sans-serif`;
              g.fillText(n + '%', mid, p[1] - Math.max(h / 2 + (i ? 14 : 16), Math.abs(mid - p[0]) < rr + 40 ? rr + 12 : 0));
              g.fillStyle = '#8a96a8'; g.font = "700 10px Inter,system-ui,sans-serif"; g.fillText(lab, mid, p[1] + Math.max(h / 2 + 18, Math.abs(mid - p[0]) < rr + 30 ? rr + 18 : 0));
              xx += wTot * P1X2[i];
            });
            g.globalAlpha = 1;
          }
          g.globalCompositeOperation = 'lighter';
        }
      }

      // lime fills the lower half of the circle up to the line, with a wave that settles
      if(fill > 0){
        const p = P(0, 0), r = rr - 1, f = easeOut(fill), level = p[1] + r * (1 - f), amp = 5 * (1 - f) * Math.sin(fill * Math.PI);
        g.save(); g.beginPath(); g.arc(p[0], p[1], r, 0, Math.PI); g.closePath(); g.clip();
        g.beginPath(); g.moveTo(p[0] - r, p[1] + r + 2);
        for(let i = 0; i <= 40; i++){ const x = p[0] - r + 2 * r * i / 40; g.lineTo(x, Math.max(p[1], level + Math.sin(i / 40 * Math.PI * 3 + t * 9) * amp)) }
        g.lineTo(p[0] + r, p[1] + r + 2); g.closePath();
        g.globalCompositeOperation = 'source-over'; g.fillStyle = lime; g.globalAlpha = .96; g.fill(); g.globalAlpha = 1; g.restore();
        g.globalCompositeOperation = 'lighter';
      }

      // a flash on the line the moment the mark is complete
      const flash = seg(t, 3.05, 3.4);
      if(flash > 0 && flash < 1){
        const p = P(0, 0), k = Math.sin(flash * Math.PI), gr = g.createRadialGradient(p[0], p[1], 0, p[0], p[1], R * 3.2);
        gr.addColorStop(0, `rgba(214,255,140,${.28 * k})`); gr.addColorStop(1, 'rgba(194,242,94,0)');
        g.fillStyle = gr; g.fillRect(0, 0, W, H);
      }
      g.globalCompositeOperation = 'source-over';

      // title and exit
      if(t > 2.9 && !el.classList.contains('word')) el.classList.add('word');
      if(t > 3.2 && !el.classList.contains('shine')) el.classList.add('shine');
      if(t >= exitAt){
        const k = easeIn(seg(t, exitAt, exitAt + .65)), p = P(0, 0);
        const r = lerp(R - 1, Math.hypot(W, H) * 1.05, k);
        const m = `radial-gradient(circle at ${p[0]}px ${p[1]}px, transparent ${r}px, #000 ${r + 1.5}px)`;
        el.style.webkitMaskImage = m; el.style.maskImage = m;
        g.globalCompositeOperation = 'lighter';
        g.strokeStyle = lime; g.globalAlpha = .25 * (1 - k); g.lineWidth = 16; g.beginPath(); g.arc(p[0], p[1], r + 6, 0, 7); g.stroke();
        g.strokeStyle = chalk; g.globalAlpha = 1 - k * .6; g.lineWidth = 3; g.beginPath(); g.arc(p[0], p[1], r + 2.5, 0, 7); g.stroke();
        g.globalAlpha = 1; g.globalCompositeOperation = 'source-over';
        if(!el.classList.contains('end')) el.classList.add('end');
        title.style.opacity = String(1 - seg(t, exitAt, exitAt + .25));
        if(k >= 1){ finish(); return }
      }
      raf = requestAnimationFrame(frame);
    }
    const finish = () => { if(done) return; done = true; cancelAnimationFrame(raf); removeEventListener('resize', size); removeEventListener('keydown', key); el.remove() };
    // skip: jump to the finished mark and open the iris straight away
    const skip = () => {
      const t = (performance.now() - t0) / 1000; if(t >= exitAt) return;
      if(t < 3.2) t0 = performance.now() - 3200;
      exitAt = Math.max((performance.now() - t0) / 1000, 3.2) + .05;
    };
    const key = e => { if(['Escape', 'Enter', ' '].includes(e.key)) skip() };
    el.addEventListener('click', skip); addEventListener('keydown', key);
    requestAnimationFrame(() => el.classList.add('bars'));
    raf = requestAnimationFrame(frame);
    if(typeof hold !== 'number') setTimeout(finish, (DUR + 2) * 1000);
    else el.hold = v => { hold = v };
  }

  window.fairlineIntro = at => { try{ sessionStorage.removeItem('ko') }catch{} intro(typeof at === 'number' ? at : undefined) };
  document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', intro) : intro();
})();
