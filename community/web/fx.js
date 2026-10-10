/* Living Pitch: the animated backdrop shared by every page.
   Layers: drifting aurora, perspective pitch markings with parallax, flow-field
   particles, occasional "switch of play" comets, and a cursor glow.
   Pauses when the tab is hidden; draws one still frame when motion is reduced
   or switched off. Public API: window.LivingPitch.burst(x, y, colors), .setEnabled(bool). */
(function(){
  'use strict';
  const store = {get(k){ try{ return localStorage.getItem(k) }catch{ return null } }, set(k, v){ try{ localStorage.setItem(k, v) }catch{} }};
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const canvas = document.createElement('canvas');
  canvas.id = 'living-pitch'; canvas.setAttribute('aria-hidden', 'true');
  canvas.style.cssText = 'position:fixed;inset:0;width:100%;height:100%;z-index:-1;pointer-events:none';
  document.addEventListener('DOMContentLoaded', () => document.body.prepend(canvas));
  if(document.body) document.body.prepend(canvas);
  const ctx = canvas.getContext('2d');
  let W = 0, H = 0, dpr = 1, running = false, enabled = store.get('fx') !== 'off', last = 0, t0 = performance.now();
  const mouse = {x: 0.5, y: 0.35, tx: 0.5, ty: 0.35, seen: false};
  let scrollY = 0, particles = [], comets = [], bursts = [];

  const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#c2f25e';
  const isLight = () => getComputedStyle(document.documentElement).colorScheme.includes('light');
  function palette(){
    const light = isLight();
    return {bg: css('--bg'), a: css('--accent'), b: css('--away'), c: light ? '#b48cff' : '#a07bff', line: light ? 'rgba(16,24,40,.09)' : 'rgba(255,255,255,.085)',
      particle: light ? 'rgba(16,24,40,.32)' : 'rgba(255,255,255,.62)', glow: light ? .13 : .24, light};
  }
  let P = palette();

  function resize(){
    dpr = Math.min(1.5, devicePixelRatio || 1);
    W = innerWidth; H = innerHeight;
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const n = Math.round(Math.min(190, W * H / 6500));
    particles = Array.from({length: n}, () => spawn());
    P = palette(); frame(performance.now(), true);
  }
  const spawn = () => ({x: Math.random() * W, y: Math.random() * H, life: Math.random() * 300, max: 220 + Math.random() * 260, px: 0, py: 0});

  // A smooth, cheap flow field: layered sines give curling "runs".
  function flow(x, y, t){
    const s = 0.0016;
    return Math.sin(x * s + t * 0.00011) * 1.3 + Math.cos(y * s * 1.7 - t * 0.00008) * 1.1 + Math.sin((x + y) * s * 0.6 + t * 0.00005);
  }

  function aurora(t){
    ctx.fillStyle = P.bg; ctx.fillRect(0, 0, W, H);
    const blobs = [[P.a, 0.18, 0.12, 0.55], [P.b, 0.85, 0.2, 0.5], [P.c, 0.55, 0.95, 0.6]];
    ctx.globalCompositeOperation = P.light ? 'multiply' : 'screen';
    blobs.forEach(([col, bx, by, r], i) => {
      const x = (bx + Math.sin(t * 0.00007 + i * 2.1) * 0.08 + (mouse.x - 0.5) * 0.04 * (i + 1)) * W;
      const y = (by + Math.cos(t * 0.00006 + i * 1.7) * 0.07 + (mouse.y - 0.5) * 0.03 * (i + 1)) * H - scrollY * 0.05 * (i + 1);
      const rad = r * Math.max(W, H);
      const g = ctx.createRadialGradient(x, y, 0, x, y, rad);
      g.addColorStop(0, hexA(col, P.glow)); g.addColorStop(1, hexA(col, 0));
      ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
    });
    ctx.globalCompositeOperation = 'source-over';
  }
  function hexA(c, a){
    if(c.startsWith('#') && (c.length === 7 || c.length === 4)){
      const h = c.length === 4 ? c.slice(1).split('').map(x => x + x).join('') : c.slice(1);
      return `rgba(${parseInt(h.slice(0, 2), 16)},${parseInt(h.slice(2, 4), 16)},${parseInt(h.slice(4, 6), 16)},${a})`;
    }
    return c;
  }

  // Pitch markings seen from above-behind, drifting with cursor and scroll.
  function pitch(){
    const cx = W / 2 + (mouse.x - 0.5) * 40, horizon = H * 0.08 - scrollY * 0.12, base = H * 1.15 - scrollY * 0.2;
    const proj = (u, v) => { const k = 0.35 + 0.65 * v; return {x: cx + u * W * 0.62 * k, y: horizon + (base - horizon) * Math.pow(v, 1.35)} };
    ctx.strokeStyle = P.line; ctx.lineWidth = 1.2;
    const line = pts => { ctx.beginPath(); pts.forEach((p, i) => { const q = proj(p[0], p[1]); i ? ctx.lineTo(q.x, q.y) : ctx.moveTo(q.x, q.y) }); ctx.stroke() };
    line([[-1, 0], [1, 0], [1, 1], [-1, 1], [-1, 0]]);
    line([[-1, 0.5], [1, 0.5]]);
    ctx.beginPath();
    for(let i = 0; i <= 48; i++){ const a = i / 48 * Math.PI * 2, q = proj(Math.cos(a) * 0.17, 0.5 + Math.sin(a) * 0.1); i ? ctx.lineTo(q.x, q.y) : ctx.moveTo(q.x, q.y) }
    ctx.stroke();
    line([[-0.4, 0], [-0.4, 0.13], [0.4, 0.13], [0.4, 0]]); line([[-0.4, 1], [-0.4, 0.87], [0.4, 0.87], [0.4, 1]]);
    line([[-0.18, 0], [-0.18, 0.05], [0.18, 0.05], [0.18, 0]]); line([[-0.18, 1], [-0.18, 0.95], [0.18, 0.95], [0.18, 1]]);
  }

  function step(t, dt){
    // particles: short trails along the flow field
    ctx.lineCap = 'round';
    for(const p of particles){
      const ang = flow(p.x, p.y + scrollY * 0.3, t) * Math.PI;
      p.px = p.x; p.py = p.y;
      p.x += Math.cos(ang) * 0.55 * dt; p.y += Math.sin(ang) * 0.55 * dt;
      // the cursor gently pulls nearby runners
      if(mouse.seen){ const dx = mouse.x * W - p.x, dy = mouse.y * H - p.y, d2 = dx * dx + dy * dy; if(d2 < 32000){ p.x += dx / 600 * dt; p.y += dy / 600 * dt } }
      p.life += dt;
      if(p.life > p.max || p.x < -20 || p.x > W + 20 || p.y < -20 || p.y > H + 20){ Object.assign(p, spawn(), {life: 0}); continue }
      const fade = Math.min(1, p.life / 40, (p.max - p.life) / 40);
      ctx.strokeStyle = P.particle.replace(/[\d.]+\)$/, (parseFloat(P.particle.match(/[\d.]+\)$/)) * fade).toFixed(3) + ')');
      ctx.lineWidth = 1.7; ctx.beginPath(); ctx.moveTo(p.px, p.py); ctx.lineTo(p.x, p.y); ctx.stroke();
    }
    // comets: a ball switched across the field
    if(Math.random() < 0.007 * dt && comets.length < 3){
      const fromLeft = Math.random() < 0.5;
      comets.push({x0: fromLeft ? -40 : W + 40, y0: H * (0.2 + Math.random() * 0.5), x1: fromLeft ? W + 40 : -40, y1: H * (0.2 + Math.random() * 0.5), h: 80 + Math.random() * 140, t: 0, dur: 1600 + Math.random() * 900, col: Math.random() < 0.5 ? P.a : P.b});
    }
    comets = comets.filter(c => (c.t += dt * 16.7) < c.dur);
    for(const c of comets){
      const k = c.t / c.dur, tail = 18;
      for(let i = tail; i >= 0; i--){
        const u = Math.max(0, k - i * 0.006), x = c.x0 + (c.x1 - c.x0) * u, y = c.y0 + (c.y1 - c.y0) * u - Math.sin(u * Math.PI) * c.h;
        ctx.fillStyle = hexA(c.col, (1 - i / tail) * 0.5); ctx.beginPath(); ctx.arc(x, y, 2.6 * (1 - i / tail) + 0.6, 0, 6.283); ctx.fill();
      }
    }
    // bursts: celebration sparks from app events
    bursts = bursts.filter(b => (b.life -= dt) > 0);
    for(const b of bursts){ b.x += b.vx * dt; b.y += b.vy * dt; b.vy += 0.04 * dt; b.vx *= 0.985; ctx.fillStyle = hexA(b.col, Math.min(1, b.life / 30)); ctx.beginPath(); ctx.arc(b.x, b.y, b.r, 0, 6.283); ctx.fill() }
    // cursor glow
    if(mouse.seen){
      const g = ctx.createRadialGradient(mouse.x * W, mouse.y * H, 0, mouse.x * W, mouse.y * H, 220);
      g.addColorStop(0, hexA(P.a, P.light ? 0.08 : 0.07)); g.addColorStop(1, hexA(P.a, 0));
      ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
    }
  }

  function frame(now, still){
    const dt = Math.min(3, (now - last) / 16.7 || 1); last = now;
    mouse.x += (mouse.tx - mouse.x) * 0.06; mouse.y += (mouse.ty - mouse.y) * 0.06;
    const t = now - t0;
    aurora(t); pitch();
    if(!still) step(t, dt);
    if(running) requestAnimationFrame(f => frame(f));
  }
  function start(){ if(running || !enabled || reduced.matches || document.hidden) return; running = true; last = performance.now(); requestAnimationFrame(f => frame(f)) }
  function stop(){ running = false }
  function sync(){ (enabled && !reduced.matches && !document.hidden) ? start() : (stop(), frame(performance.now(), true)) }

  addEventListener('resize', resize);
  addEventListener('pointermove', e => { mouse.tx = e.clientX / W; mouse.ty = e.clientY / H; mouse.seen = true }, {passive: true});
  addEventListener('scroll', () => { scrollY = window.scrollY }, {passive: true});
  document.addEventListener('visibilitychange', sync);
  reduced.addEventListener('change', sync);
  // Re-read colours when the theme changes.
  new MutationObserver(() => { P = palette(); if(!running) frame(performance.now(), true) }).observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme']});
  matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => { P = palette() });

  window.LivingPitch = {
    burst(x, y, colors){
      if(!running) return;
      const cols = colors && colors.length ? colors : [P.a, P.b];
      for(let i = 0; i < 70; i++){ const a = Math.random() * Math.PI * 2, s = 1 + Math.random() * 4.5;
        bursts.push({x, y, vx: Math.cos(a) * s, vy: Math.sin(a) * s - 1.5, r: 1.2 + Math.random() * 2.4, life: 50 + Math.random() * 50, col: cols[i % cols.length]}) }
    },
    setEnabled(on){ enabled = on; store.set('fx', on ? 'on' : 'off'); sync() },
    get enabled(){ return enabled },
  };
  resize(); sync();

  // Spotlight: cards light up where the cursor is (CSS reads --mx/--my).
  addEventListener('pointermove', e => {
    const card = e.target.closest && e.target.closest('.card, .stat, .fx, .board');
    if(!card) return;
    const r = card.getBoundingClientRect();
    card.style.setProperty('--mx', (e.clientX - r.left) + 'px'); card.style.setProperty('--my', (e.clientY - r.top) + 'px');
  }, {passive: true});
})();
