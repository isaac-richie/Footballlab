/* Fairline welcome: a short film, drawn live on a canvas.
   A night match under floodlights. The camera starts low behind one goal and moves up the pitch while
   the lines draw themselves; it cranes up over the centre spot, where the halfway line and the centre
   circle become the Fairline mark and the lime fills the lower half up to the line; the name tracks in
   under a light sweep; then the camera pushes through the circle, which opens like an iris onto the app.
   Once per visit, about 4.6 s, a tap / Skip / Esc ends it. Off for prefers-reduced-motion and when the
   effects toggle is off. fairlineIntro() replays it. */
(function(){
  'use strict';
  const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
  const off = () => { try{ return localStorage.getItem('fx') === 'off' }catch{ return false } };

  const css = document.createElement('style');
  css.textContent = `
  .fl-intro{position:fixed;inset:0;z-index:1000;background:#030406;overflow:hidden;cursor:pointer;--lime:#c2f25e;
    -webkit-mask-repeat:no-repeat;mask-repeat:no-repeat}
  .fl-intro canvas{position:absolute;inset:0;width:100%;height:100%;display:block}
  .fl-vig{position:absolute;inset:0;z-index:2;pointer-events:none;background:radial-gradient(ellipse 75% 70% at 50% 50%,transparent 40%,rgba(0,0,0,.72) 100%)}
  .fl-grain{position:absolute;inset:-10%;z-index:2;pointer-events:none;opacity:.09;mix-blend-mode:overlay;
    background:repeating-radial-gradient(circle at 17% 31%,#fff 0 .6px,transparent .6px 2.4px),repeating-radial-gradient(circle at 71% 63%,#fff 0 .5px,transparent .5px 3.1px);
    animation:flGrain .18s steps(3) infinite}
  @keyframes flGrain{33%{transform:translate(-2%,1%)}66%{transform:translate(1%,-2%)}}
  .fl-bar{position:absolute;left:0;right:0;height:10.5vh;background:#000;z-index:4;transition:transform .7s cubic-bezier(.7,0,.2,1)}
  .fl-bar.t{top:0;transform:translateY(-100%)}
  .fl-bar.b{bottom:0;transform:translateY(100%)}
  .fl-intro.bars .fl-bar{transform:none}
  .fl-intro.end .fl-bar{transition-duration:.55s}
  .fl-intro.end .fl-bar.t{transform:translateY(-100%)}
  .fl-intro.end .fl-bar.b{transform:translateY(100%)}
  .fl-skip{position:absolute;right:max(18px,env(safe-area-inset-right));bottom:3.6vh;z-index:5;padding:6px 2px;border:0;background:none;cursor:pointer;
    font:600 11px/1 Inter,system-ui,sans-serif;letter-spacing:3px;text-transform:uppercase;color:#7d8899;opacity:0;transition:opacity .5s .8s,color .2s}
  .fl-skip:hover{color:#e9eef4}
  .fl-intro.bars .fl-skip{opacity:1}
  .fl-intro.end .fl-skip{opacity:0;transition-delay:0s}
  .fl-title{position:absolute;left:0;right:0;z-index:3;display:grid;justify-items:center;gap:14px;pointer-events:none}
  .fl-word{position:relative;display:flex;font:800 clamp(50px,14vw,112px)/.9 'Barlow Condensed','Arial Narrow',sans-serif;text-transform:uppercase;
    color:#eef2f7;letter-spacing:.5em;margin-right:-.5em;transition:letter-spacing 1.1s cubic-bezier(.16,1,.3,1),margin 1.1s cubic-bezier(.16,1,.3,1)}
  .fl-word span{display:inline-block;opacity:0;transform:translateY(.28em) scale(1.12);filter:blur(14px);
    transition:opacity .7s ease,transform 1s cubic-bezier(.16,1,.3,1),filter .8s ease;transition-delay:calc(var(--i) * 55ms)}
  .fl-word span.l{color:var(--lime);text-shadow:0 0 34px rgba(194,242,94,.32)}
  .fl-word::after{content:attr(data-t);position:absolute;inset:0;display:flex;letter-spacing:inherit;color:#fff;pointer-events:none;
    -webkit-mask-image:linear-gradient(105deg,transparent 35%,#000 48%,#000 52%,transparent 65%);mask-image:linear-gradient(105deg,transparent 35%,#000 48%,#000 52%,transparent 65%);
    -webkit-mask-size:300% 100%;mask-size:300% 100%;-webkit-mask-position:120% 0;mask-position:120% 0;opacity:0;mix-blend-mode:screen}
  .fl-intro.word .fl-word{letter-spacing:.05em;margin-right:-.05em}
  .fl-intro.word .fl-word span{opacity:1;transform:none;filter:blur(0)}
  .fl-intro.shine .fl-word::after{opacity:.9;animation:flShine 1.1s cubic-bezier(.4,0,.2,1) forwards}
  @keyframes flShine{from{-webkit-mask-position:120% 0;mask-position:120% 0}to{-webkit-mask-position:-20% 0;mask-position:-20% 0}}
  .fl-tag{font:600 clamp(11px,2.9vw,13px)/1 Inter,system-ui,sans-serif;letter-spacing:.9em;text-transform:uppercase;color:#8a96a8;opacity:0;
    transition:opacity 1s ease .35s,letter-spacing 1.4s cubic-bezier(.16,1,.3,1) .2s}
  .fl-intro.word .fl-tag{opacity:1;letter-spacing:.42em}`;
  document.head.appendChild(css);

  // ---- easing and timeline helpers
  const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
  const lerp = (a, b, t) => a + (b - a) * t;
  const ease = t => t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;      // in-out cubic
  const easeOut = t => 1 - Math.pow(1 - t, 3);
  const easeIn = t => t * t * t;
  const seg = (t, a, b) => clamp((t - a) / (b - a));                                   // 0..1 progress of t through [a, b]

  // ---- the pitch, in metres: x across (±34), z along (±52.5), y up
  const L = 52.5, Wd = 34;
  const line = (x1, z1, x2, z2, n = 26) => Array.from({length: n + 1}, (_, i) => [lerp(x1, x2, i / n), lerp(z1, z2, i / n)]);
  const arc = (cx, cz, r, a0, a1, n = 72) => Array.from({length: n + 1}, (_, i) => { const a = lerp(a0, a1, i / n); return [cx + r * Math.cos(a), cz + r * Math.sin(a)] });
  const box = (s, w, d) => [[-w, s * L], [-w, s * (L - d)], [w, s * (L - d)], [w, s * L]].reduce((pts, p, i, a) => i ? pts.concat(line(a[i - 1][0], a[i - 1][1], p[0], p[1], 12).slice(1)) : [p], []);
  // each mark: points, when it starts drawing, how long it takes, whether it survives into the logo
  const MARKS = [
    {pts: line(-Wd, -L, -Wd, L, 60), at: .55, dur: 1.2},
    {pts: line(Wd, -L, Wd, L, 60), at: .6, dur: 1.2},
    {pts: line(-Wd, -L, Wd, -L), at: .45, dur: .6},
    {pts: line(-Wd, L, Wd, L), at: 1.3, dur: .7},
    {pts: box(-1, 20.16, 16.5), at: .7, dur: .6},
    {pts: box(-1, 9.16, 5.5), at: .8, dur: .45},
    {pts: box(1, 20.16, 16.5), at: 1.35, dur: .6},
    {pts: box(1, 9.16, 5.5), at: 1.45, dur: .45},
    {pts: arc(0, -L + 11, 9.15, .93, Math.PI - .93, 24), at: 1.0, dur: .4},
    {pts: arc(0, L - 11, 9.15, Math.PI + .93, 2 * Math.PI - .93, 24), at: 1.5, dur: .4},
    {pts: line(-Wd, 0, Wd, 0, 40), at: 1.05, dur: .7, keep: 'line'},
    {pts: arc(0, 0, 9.15, Math.PI, -Math.PI, 120), at: 1.15, dur: .9, keep: 'ring'},
  ];
  const LIGHTS = [[-48, 34, -64, .25], [48, 34, -64, .42], [-48, 34, 64, .62], [48, 34, 64, .74]];   // x, y, z, switch-on time
  // the stands: a raked bowl from just outside the pitch (ground) up and out (top), round a rounded rectangle
  const RIM = (() => {
    const pts = [], a = Wd + 7, b = L + 7, r = 10, n = 18;
    const corner = (cx, cz, a0) => { for(let i = 0; i <= n; i++){ const t = a0 + i / n * Math.PI / 2; pts.push([cx + r * Math.cos(t), cz + r * Math.sin(t)]) } };
    corner(a - r, b - r, 0); corner(-a + r, b - r, Math.PI / 2); corner(-a + r, -b + r, Math.PI); corner(a - r, -b + r, 1.5 * Math.PI);
    return pts.map(([x, z]) => { const len = Math.hypot(x, z); return {x, z, ox: x + x / len * 34, oz: z + z / len * 34} });
  })();
  const CROWD = Array.from({length: 640}, () => { const i = Math.floor(Math.random() * RIM.length), v = .15 + Math.random() * .8, q = RIM[i];
    return {x: lerp(q.x, q.ox, v), y: v * 26, z: lerp(q.z, q.oz, v), ph: Math.random(), rate: .6 + Math.random() * 1.8} });

  function intro(hold){
    let seen = false; try{ seen = sessionStorage.getItem('ko') === '1'; sessionStorage.setItem('ko', '1') }catch{}
    if(hold == null && (seen || reduced() || off())) return;
    if(document.querySelector('.fl-intro')) return;

    const el = document.createElement('div');
    el.className = 'fl-intro'; el.setAttribute('aria-hidden', 'true');
    const letters = [...'FAIRLINE'].map((c, i) => `<span${i > 3 ? ' class="l"' : ''} style="--i:${i}">${c}</span>`).join('');
    el.innerHTML = `<canvas></canvas><div class="fl-vig"></div><div class="fl-grain"></div>
      <div class="fl-title"><div class="fl-word" data-t="FAIRLINE">${letters}</div><div class="fl-tag">The fair price on every game</div></div>
      <i class="fl-bar t"></i><i class="fl-bar b"></i><button class="fl-skip" type="button" tabindex="-1">Skip</button>`;
    document.body.appendChild(el);
    const cv = el.querySelector('canvas'), g = cv.getContext('2d'), title = el.querySelector('.fl-title');
    let W = 0, H = 0, dpr = 1, fl = 1, R = 60, Hf = 40, dz = 0, cy = 0;
    const size = () => {
      dpr = Math.min(devicePixelRatio || 1, 2); W = innerWidth; H = innerHeight;
      cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); g.setTransform(dpr, 0, 0, dpr, 0, 0);
      fl = Math.min(W, H) * (W > H ? .78 : .95);         // focal length in px: a wider lens on landscape screens
      R = clamp(Math.min(W, H) * .15, 52, 96);          // the mark's radius on screen at the end
      Hf = 9.15 * fl / R;                                // camera height that makes the centre circle exactly R
      cy = H * .5 - Math.min(H * .13, 120);              // where the mark sits: a little above centre, to leave room for the name
      dz = (H * .5 - cy) * Hf / fl;                      // camera offset along the pitch that puts it there
      title.style.top = (cy + R + Math.max(26, R * .42)) + 'px';
    };
    size(); addEventListener('resize', size);

    // dust in the light: fixed 3D positions that drift
    const dust = Array.from({length: 140}, () => ({x: (Math.random() - .5) * 110, y: Math.random() * 22, z: (Math.random() - .5) * 140, s: Math.random() * 1.4 + .4, v: Math.random() * .6 + .2}));

    // camera: behind one goal, low; then up the pitch with a little drift to the side; then a crane over the centre spot
    const camera = t => {
      const a = ease(seg(t, 0, 1.75)), b = ease(seg(t, 1.45, 2.75));
      // from low by the corner flag, looking across the pitch, swinging round to face up the middle
      const p1 = {x: lerp(-46, -6, a), y: lerp(3.2, 15, a), z: lerp(-74, -46, a), th: lerp(.1, .4, a), yaw: lerp(.62, .08, a)};
      return {x: lerp(p1.x, 0, b), y: lerp(p1.y, Hf, b), z: lerp(p1.z, -dz, b), th: lerp(p1.th, Math.PI / 2, b), yaw: lerp(p1.yaw, 0, b)};
    };
    let C, sn, cs, sy, cyw;
    const proj = (x, y, z) => {
      const ex = x - C.x, dy = y - C.y, ez = z - C.z;
      const dx = ex * cyw - ez * sy, dz2 = ex * sy + ez * cyw;          // turn (yaw), then tilt (pitch)
      const zc = -dy * sn + dz2 * cs, yc = dy * cs + dz2 * sn;
      if(zc < .8) return null;
      return [W / 2 + dx * fl / zc, H / 2 - yc * fl / zc, zc];
    };
    const stroke = (pts, frac, col, alpha, glow) => {
      const n = Math.max(0, Math.floor((pts.length - 1) * frac)) + 1;
      if(n < 2 || alpha <= 0) return;
      g.beginPath(); let pen = false;
      for(let i = 0; i < n; i++){ const p = proj(pts[i][0], 0, pts[i][1]); if(!p){ pen = false; continue } pen ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1]); pen = true }
      g.strokeStyle = col;
      if(glow){ g.globalAlpha = alpha * .16; g.lineWidth = glow; g.stroke() }
      g.globalAlpha = alpha; g.lineWidth = 1.6; g.stroke(); g.globalAlpha = 1;
    };
    const flare = (sx, sy, k, s) => {
      // soft core, a wide anamorphic streak and a faint ghost: what a lens does with a floodlight
      let r = s * 70 * k;
      let gr = g.createRadialGradient(sx, sy, 0, sx, sy, r);
      gr.addColorStop(0, `rgba(255,255,255,${.95 * k})`); gr.addColorStop(.18, `rgba(220,236,255,${.55 * k})`); gr.addColorStop(1, 'rgba(160,200,255,0)');
      g.fillStyle = gr; g.beginPath(); g.arc(sx, sy, r, 0, 7); g.fill();
      g.save(); g.translate(sx, sy); g.scale(1, .035);
      r = W * .55 * k; gr = g.createRadialGradient(0, 0, 0, 0, 0, r);
      gr.addColorStop(0, `rgba(190,220,255,${.5 * k})`); gr.addColorStop(1, 'rgba(120,170,255,0)');
      g.fillStyle = gr; g.beginPath(); g.arc(0, 0, r, 0, 7); g.fill(); g.restore();
      const gx = W - sx, gy = H - sy; gr = g.createRadialGradient(gx, gy, 0, gx, gy, s * 26);
      gr.addColorStop(0, `rgba(194,242,94,${.07 * k})`); gr.addColorStop(1, 'rgba(194,242,94,0)');
      g.fillStyle = gr; g.beginPath(); g.arc(gx, gy, s * 26, 0, 7); g.fill();
    };

    const DUR = 4.6, EXIT = 3.85;
    let t0 = performance.now(), exitAt = EXIT, raf = 0, done = false;
    const lime = '#c2f25e', chalk = '#e9eef4';

    function frame(now){
      const t = typeof hold === 'number' ? hold : (now - t0) / 1000;
      C = camera(Math.min(t, 2.75)); sn = Math.sin(C.th); cs = Math.cos(C.th); sy = Math.sin(C.yaw); cyw = Math.cos(C.yaw);
      g.globalCompositeOperation = 'source-over';
      // night sky to grass
      const sky = g.createLinearGradient(0, 0, 0, H); sky.addColorStop(0, '#0b1220'); sky.addColorStop(.55, '#05070b'); sky.addColorStop(1, '#060a08');
      g.fillStyle = sky; g.fillRect(0, 0, W, H);

      const lit = LIGHTS.map(([, , , on]) => { const k = seg(t, on, on + .12); return k < 1 ? (Math.sin(k * 40) > -.2 ? k : k * .3) : 1 });   // flicker on
      const lights = lit.reduce((a, b) => a + b, 0) / 4;
      const crane = seg(t, 1.9, 2.6);                      // 0 while on the pitch, 1 once looking straight down
      const pitchFade = 1 - ease(seg(t, 2.15, 2.75));      // everything but the mark fades as we crane up

      // the stands, dark against the night, their rim catching the light
      if(pitchFade > 0){
        g.fillStyle = `rgb(${14 + 8 * lights | 0},${18 + 10 * lights | 0},${26 + 12 * lights | 0})`; g.globalAlpha = pitchFade;
        for(let i = 0; i < RIM.length; i++){
          const A = RIM[i], B = RIM[(i + 1) % RIM.length];
          const q = [proj(A.x, 0, A.z), proj(B.x, 0, B.z), proj(B.ox, 26, B.oz), proj(A.ox, 26, A.oz)];
          if(q.some(p => !p)) continue;
          g.beginPath(); q.forEach((p, k) => k ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1])); g.closePath(); g.fill();
        }
        g.strokeStyle = 'rgba(170,195,230,.35)'; g.lineWidth = 1; g.beginPath(); let pen = false;
        for(let i = 0; i <= RIM.length; i++){ const A = RIM[i % RIM.length], p = proj(A.ox, 26, A.oz); if(!p){ pen = false; continue } pen ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1]); pen = true }
        g.globalAlpha = pitchFade * lights; g.stroke(); g.globalAlpha = 1;
        // phone flashes in the crowd
        g.globalCompositeOperation = 'lighter';
        for(const c of CROWD){
          const ph = (t * c.rate + c.ph) % 1; if(ph > .07) continue;
          const p = proj(c.x, c.y, c.z); if(!p) continue;
          const k = (1 - ph / .07) * pitchFade * clamp(lights * 1.4), r = clamp(40 / p[2], .6, 3);
          g.fillStyle = `rgba(255,248,235,${k})`; g.beginPath(); g.arc(p[0], p[1], r, 0, 7); g.fill();
          g.fillStyle = `rgba(255,248,235,${k * .18})`; g.beginPath(); g.arc(p[0], p[1], r * 4, 0, 7); g.fill();
        }
        g.globalCompositeOperation = 'source-over';
      }

      // mowing stripes, lit by the floodlights
      for(let i = 0; i < 14; i++){
        const z1 = -L + i * (2 * L / 14), z2 = z1 + 2 * L / 14, q = [proj(-Wd, 0, z1), proj(Wd, 0, z1), proj(Wd, 0, z2), proj(-Wd, 0, z2)];
        if(q.some(p => !p)) continue;
        g.fillStyle = i % 2 ? '#12241a' : '#0d1b12'; g.globalAlpha = lights * (.12 + .88 * pitchFade);
        g.beginPath(); q.forEach((p, k) => k ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1])); g.closePath(); g.fill();
      }
      g.globalAlpha = 1;
      // pool of light on the grass
      const c0 = proj(0, 0, 0);
      if(c0){ const r = Math.max(W, H) * .8, gr = g.createRadialGradient(c0[0], c0[1], 0, c0[0], c0[1], r);
        gr.addColorStop(0, `rgba(120,160,120,${.10 * lights})`); gr.addColorStop(1, 'rgba(0,0,0,0)'); g.fillStyle = gr; g.fillRect(0, 0, W, H) }

      // light falling from each floodlight onto the grass
      g.globalCompositeOperation = 'lighter';
      LIGHTS.forEach(([x, y, z], i) => {
        const k = lit[i] * pitchFade * (1 - crane); if(k <= .01) return;
        const s0 = proj(x, y, z), a = proj(x * .1 - 14, 0, z * .2), b = proj(x * .1 + 14, 0, z * .2);
        if(!s0 || !a || !b) return;
        const gr = g.createLinearGradient(s0[0], s0[1], (a[0] + b[0]) / 2, (a[1] + b[1]) / 2);
        gr.addColorStop(0, `rgba(200,220,255,${.10 * k})`); gr.addColorStop(1, 'rgba(200,220,255,0)');
        g.fillStyle = gr; g.beginPath(); g.moveTo(s0[0], s0[1]); g.lineTo(a[0], a[1]); g.lineTo(b[0], b[1]); g.closePath(); g.fill();
      });

      // the lines
      g.globalCompositeOperation = 'lighter'; g.lineCap = 'round'; g.lineJoin = 'round';
      for(const m of MARKS){
        const f = easeOut(seg(t, m.at, m.at + m.dur));
        if(!m.keep){ stroke(m.pts, f, chalk, .75 * pitchFade, 5); continue }
        const col = m.keep === 'line' ? lime : chalk, a = lerp(.8, 1, crane);
        stroke(m.pts, f, col, a, lerp(5, 12, crane));
      }

      // the lime filling the lower half of the circle up to the line
      const fill = easeOut(seg(t, 2.5, 3.05));
      if(fill > 0){
        const level = lerp(-9.15, 0, fill);
        g.globalCompositeOperation = 'source-over'; g.beginPath(); let first = true;
        for(let i = 0; i <= 60; i++){
          const a = Math.PI + i / 60 * Math.PI, x = 9.15 * Math.cos(a), z = 9.15 * Math.sin(a);   // lower half: z from 0 down to -9.15
          if(z > level) continue;
          const p = proj(x, 0, z); if(!p) continue; first ? g.moveTo(p[0], p[1]) : g.lineTo(p[0], p[1]); first = false;
        }
        const w = Math.sqrt(Math.max(0, 9.15 * 9.15 - level * level)), pa = proj(w, 0, level), pb = proj(-w, 0, level);
        if(pa && pb){ g.lineTo(pa[0], pa[1]); g.lineTo(pb[0], pb[1]) }
        g.closePath(); g.fillStyle = lime; g.globalAlpha = .96; g.fill();
        g.globalAlpha = 1; g.globalCompositeOperation = 'lighter';
      }

      // the fair line runs out to the edges of the frame
      const out = easeOut(seg(t, 2.75, 3.3));
      if(out > 0){
        const p = proj(0, 0, 0);
        if(p){
          const half = lerp(R, W * .5, out);
          const gr = g.createLinearGradient(p[0] - half, 0, p[0] + half, 0);
          gr.addColorStop(0, 'rgba(194,242,94,0)'); gr.addColorStop(.15, lime); gr.addColorStop(.85, lime); gr.addColorStop(1, 'rgba(194,242,94,0)');
          g.strokeStyle = gr; g.globalAlpha = .2; g.lineWidth = 10; g.beginPath(); g.moveTo(p[0] - half, p[1]); g.lineTo(p[0] + half, p[1]); g.stroke();
          g.globalAlpha = 1; g.lineWidth = 1.8; g.stroke();
        }
      }

      // dust drifting through the beams
      if(pitchFade > 0) for(const d of dust){
        const p = proj(d.x + Math.sin(t * d.v + d.z) * 1.2, d.y + (t * d.v) % 3, d.z); if(!p) continue;
        const a = clamp(1 - p[2] / 140) * .5 * lights * pitchFade; if(a < .02) continue;
        g.fillStyle = `rgba(230,240,255,${a})`; g.fillRect(p[0], p[1], d.s, d.s);
      }

      // floodlights and their lens flares
      LIGHTS.forEach(([x, y, z], i) => {
        const k = lit[i] * pitchFade * (1 - crane * .9); if(k <= .01) return;
        const p = proj(x, y, z); if(!p || p[0] < -W || p[0] > 2 * W || p[1] < -H) return;
        flare(p[0], p[1], k, clamp(60 / p[2], .35, 1.6));
      });
      g.globalCompositeOperation = 'source-over';

      // title and exit
      if(t > 2.85 && !el.classList.contains('word')) el.classList.add('word');
      if(t > 3.25 && !el.classList.contains('shine')) el.classList.add('shine');
      if(t >= exitAt){
        // push through the circle: it opens like an iris onto the app
        const k = easeIn(seg(t, exitAt, exitAt + .75)), p = proj(0, 0, 0) || [W / 2, cy];
        const r = lerp(R - 1, Math.hypot(W, H) * 1.05, k);
        const m = `radial-gradient(circle at ${p[0]}px ${p[1]}px, transparent ${r}px, #000 ${r + 1.5}px)`;
        el.style.webkitMaskImage = m; el.style.maskImage = m;
        // the centre circle rides the edge of the opening: we are flying through it
        g.globalCompositeOperation = 'lighter';
        g.strokeStyle = lime; g.globalAlpha = .25 * (1 - k); g.lineWidth = 16; g.beginPath(); g.arc(p[0], p[1], r + 6, 0, 7); g.stroke();
        g.strokeStyle = chalk; g.globalAlpha = 1 - k * .6; g.lineWidth = 3; g.beginPath(); g.arc(p[0], p[1], r + 2.5, 0, 7); g.stroke();
        g.globalAlpha = 1; g.globalCompositeOperation = 'source-over';
        if(!el.classList.contains('end')) el.classList.add('end');
        title.style.opacity = String(1 - seg(t, exitAt, exitAt + .3));
        if(k >= 1){ finish(); return }
      }
      raf = requestAnimationFrame(frame);
    }
    const finish = () => { if(done) return; done = true; cancelAnimationFrame(raf); removeEventListener('resize', size); removeEventListener('keydown', key); el.remove() };
    // skip: jump to the finished logo (camera overhead, mark filled) and open the iris straight away
    const skip = () => {
      const t = (performance.now() - t0) / 1000; if(t >= exitAt) return;
      if(t < 3.05) t0 = performance.now() - 3050;
      exitAt = Math.max((performance.now() - t0) / 1000, 3.05) + .05;
    };
    const key = e => { if(['Escape', 'Enter', ' '].includes(e.key)) skip() };
    el.addEventListener('click', skip); addEventListener('keydown', key);
    requestAnimationFrame(() => el.classList.add('bars'));
    raf = requestAnimationFrame(frame);
    if(typeof hold !== 'number') setTimeout(finish, (DUR + 2) * 1000);   // never leave it on screen
    else el.hold = v => { hold = v };                                  // for checking single frames
  }

  // fairlineIntro() replays it; fairlineIntro(2.5) holds the frame at 2.5 s (el.hold(t) moves it)
  window.fairlineIntro = at => { try{ sessionStorage.removeItem('ko') }catch{} intro(typeof at === 'number' ? at : undefined) };
  document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', intro) : intro();
})();
