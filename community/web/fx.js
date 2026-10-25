/* Stadium: the drawn backdrop shared by every page.
   Each page gets its own scene, painted once into an offscreen canvas:
     stadium  night stadium from a high halfway-line camera (Featured, community home)
     aerial   the pitch from above with floodlight pools (Fixtures, Performance, games)
     goal     low camera behind the net looking up the pitch (Match)
     dusk     the stadium under an evening sky (Season, Parlay, Terrace)
   Light theme paints daytime versions. On top, cheap animated layers: a slow camera
   drift, floodlight beams through haze, crowd camera flashes, a ball switched across
   the field and celebration bursts. Runs at ~30 fps, pauses when the tab is hidden,
   and draws one still frame when motion is reduced or switched off.
   Public API (unchanged): window.LivingPitch.burst(x, y, colors), .setEnabled(bool), .enabled,
   plus .setScene(name). Pages can also set <body data-scene="…">. */
(function(){
  'use strict';
  const store = {get(k){ try{ return localStorage.getItem(k) }catch{ return null } }, set(k, v){ try{ localStorage.setItem(k, v) }catch{} }};
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const canvas = document.createElement('canvas');
  canvas.id = 'living-pitch'; canvas.setAttribute('aria-hidden', 'true');
  // A soft blur keeps the stadium as atmosphere, like a photo behind frosted glass.
  canvas.style.cssText = 'position:fixed;inset:0;width:100%;height:100%;z-index:-1;pointer-events:none;filter:blur(3px) saturate(1.1)';
  const mount = () => { if(document.body && !canvas.isConnected) document.body.prepend(canvas) };
  document.addEventListener('DOMContentLoaded', mount); mount();
  const ctx = canvas.getContext('2d');
  let W = 0, H = 0, dpr = 1, running = false, enabled = store.get('fx') !== 'off', last = 0, skip = false;
  const t0 = performance.now();
  const mouse = {x: 0.5, y: 0.4, tx: 0.5, ty: 0.4};
  let scrollY = 0, comets = [], bursts = [], flashes = [];

  const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const isLight = () => getComputedStyle(document.documentElement).colorScheme.includes('light');
  function hexA(c, a){
    if(c && c.startsWith('#') && (c.length === 7 || c.length === 4)){
      const h = c.length === 4 ? c.slice(1).split('').map(x => x + x).join('') : c.slice(1);
      return `rgba(${parseInt(h.slice(0, 2), 16)},${parseInt(h.slice(2, 4), 16)},${parseInt(h.slice(4, 6), 16)},${a})`;
    }
    return c || `rgba(194,242,94,${a})`;
  }
  // Deterministic randomness so a scene looks the same after every resize.
  function rng(seed){ return () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296 } }

  /* ---------- Which scene for this page ---------- */
  function sceneFor(){
    if(document.body && document.body.dataset.scene) return document.body.dataset.scene;
    const path = location.pathname, hash = (location.hash || '').slice(1);
    if(/\/match\//.test(path)) return 'goal';
    if(/\/social\//.test(path)) return 'dusk';
    if(/\/game\//.test(path)) return 'aerial';
    const byHash = {featured: 'stadium', fixtures: 'aerial', match: 'goal', season: 'dusk', parlay: 'dusk', performance: 'aerial',
                    play: 'stadium', table: 'aerial', results: 'aerial', leagues: 'dusk'};
    return byHash[hash] || 'stadium';
  }

  /* ---------- Palettes ---------- */
  function palette(scene){
    const light = isLight(), dusk = scene === 'dusk';
    const accent = css('--accent') || '#c2f25e', away = css('--away') || '#74bdfc';
    if(light) return {light, accent, away, bg: css('--bg') || '#f3f5f8',
      sky: ['#8fbfec', '#cfe4f7', '#eef5fb'], stand: '#5b6575', standLit: '#8792a3', roof: '#3a4250',
      grass: ['#4f9a3c', '#5aa845'], line: 'rgba(255,255,255,.85)', haze: 'rgba(255,255,255,0)', beam: 0,
      crowd: ['#2e3542', '#c94b4b', '#e9ecf1', '#3b6fb6', '#e0b13c', '#4b5563'], overlay: [.52, .66], lamp: 0};
    if(dusk) return {light, accent, away, bg: css('--bg') || '#0a0d12',
      sky: ['#140c26', '#4a2347', '#d0683f'], stand: '#120f18', standLit: '#2a2230', roof: '#08070c',
      grass: ['#21592a', '#2b6c33'], line: 'rgba(255,255,255,.6)', haze: 'rgba(255,170,110,.14)', beam: .55,
      crowd: ['#1b1720', '#3a2b35', '#8a3b36', '#2f4a80', '#7a6440', '#e4d6c8'], overlay: [.46, .70], lamp: .8, open: true};
    return {light, accent, away, bg: css('--bg') || '#0a0d12',
      sky: ['#03050a', '#0a1120', '#142238'], stand: '#0c1018', standLit: '#1c2433', roof: '#05070b',
      grass: ['#1e6129', '#2a7a35'], line: 'rgba(255,255,255,.7)', haze: 'rgba(200,220,255,.09)', beam: 1,
      crowd: ['#141a24', '#2a3242', '#8f2c34', '#2a52a0', '#6e6034', '#d9e0ea'], overlay: [.44, .68], lamp: 1};
  }

  /* ---------- Painting helpers (offscreen, once per scene and size) ---------- */
  function crowd(g, poly, P, rand, density, scaleAt, seats){
    // Fill a polygon with a crowd: rows of small coloured heads, larger towards the camera.
    const xs = poly.map(p => p[0]), ys = poly.map(p => p[1]);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    g.save(); g.beginPath(); poly.forEach((p, i) => i ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1])); g.closePath(); g.clip();
    g.fillStyle = P.stand; g.fillRect(x0, y0, x1 - x0, y1 - y0);
    const kits = P.light ? ['#c94b4b', '#3b6fb6', '#e9ecf1', '#2e3542'] : ['#8f2c34', '#2a52a0', '#cfd6e0', '#141a24', '#b8902e', '#2a3242'];
    const sections = Array.from({length: 9}, () => kits[Math.floor(rand() * kits.length)]);
    for(let y = y0; y < y1;){
      const s = scaleAt(y), step = Math.max(1.6, 3.2 * s);
      // tier shading: alternate darker/lighter bands like stepped rows
      g.fillStyle = (Math.floor((y - y0) / (step * 6)) % 2) ? P.standLit : P.stand; g.globalAlpha = .5; g.fillRect(x0, y, x1 - x0, step); g.globalAlpha = 1;
      for(let x = x0 + rand() * step; x < x1; x += step * (0.9 + rand() * 0.4)){
        if(rand() > density) continue;
        // blocks of supporters share a colour (home end, away end, neutrals)
        const block = sections[Math.floor((x - x0) / Math.max(40, (x1 - x0) / sections.length)) % sections.length];
        const c = rand() < 0.55 ? block : P.crowd[Math.floor(rand() * P.crowd.length)], r = Math.max(.7, 1.15 * s * (0.8 + rand() * 0.4));
        g.fillStyle = c; g.globalAlpha = 0.55 + rand() * 0.45; g.fillRect(x, y + rand() * step * .3, r * 1.4, r * 1.6);
        if(seats && rand() < 0.012) seats.push([x / W, y / H, s]);
      }
      y += step;
    }
    g.globalAlpha = 1; g.restore();
  }
  function stripes(g, proj, P, n){
    for(let i = 0; i < n; i++){
      const v0 = i / n, v1 = (i + 1) / n;
      const a = proj(-1.6, v0), b = proj(1.6, v0), c = proj(1.6, v1), d = proj(-1.6, v1);
      g.fillStyle = P.grass[i % 2]; g.beginPath(); g.moveTo(a.x, a.y); g.lineTo(b.x, b.y); g.lineTo(c.x, c.y); g.lineTo(d.x, d.y); g.closePath(); g.fill();
    }
  }
  function markings(g, proj, P, width){
    g.strokeStyle = P.line; g.lineWidth = width; g.lineJoin = 'round';
    const line = pts => { g.beginPath(); pts.forEach((p, i) => { const q = proj(p[0], p[1]); i ? g.lineTo(q.x, q.y) : g.moveTo(q.x, q.y) }); g.stroke() };
    line([[-1, 0], [1, 0], [1, 1], [-1, 1], [-1, 0]]); line([[-1, 0.5], [1, 0.5]]);
    g.beginPath(); for(let i = 0; i <= 64; i++){ const a = i / 64 * Math.PI * 2, q = proj(Math.cos(a) * 0.18, 0.5 + Math.sin(a) * 0.087); i ? g.lineTo(q.x, q.y) : g.moveTo(q.x, q.y) } g.stroke();
    for(const e of [0, 1]){ const s = e ? -1 : 1;
      line([[-0.44, e], [-0.44, e + s * 0.157], [0.44, e + s * 0.157], [0.44, e]]); line([[-0.2, e], [-0.2, e + s * 0.052], [0.2, e + s * 0.052], [0.2, e]]);
      g.beginPath(); for(let i = 0; i <= 24; i++){ const a = Math.PI * (0.2 + 0.6 * i / 24) * (e ? -1 : 1), q = proj(Math.cos(a) * 0.18, e + s * 0.105 + Math.sin(a) * 0.087 * (e ? -1 : 1) * -1); i ? g.lineTo(q.x, q.y) : g.moveTo(q.x, q.y) } g.stroke();
    }
  }
  function lightPool(g, x, y, r, a, col){ const gr = g.createRadialGradient(x, y, 0, x, y, r); gr.addColorStop(0, col.replace('A', a)); gr.addColorStop(1, col.replace('A', 0)); g.fillStyle = gr; g.fillRect(x - r, y - r, r * 2, r * 2) }
  function lampBank(g, x, y, s, P){
    if(!P.lamp) return;
    lightPool(g, x, y, 140 * s, .35 * P.lamp, 'rgba(255,246,220,A)');
    g.fillStyle = '#0b0d12'; g.fillRect(x - 26 * s, y - 12 * s, 52 * s, 24 * s);
    for(let r = 0; r < 3; r++) for(let c = 0; c < 6; c++){ g.fillStyle = 'rgba(255,252,240,.95)'; g.beginPath(); g.arc(x - 20 * s + c * 8 * s, y - 6 * s + r * 6.5 * s, 2.2 * s, 0, 6.283); g.fill() }
    lightPool(g, x, y, 46 * s, .8 * P.lamp, 'rgba(255,255,248,A)');
  }

  /* ---------- Scenes ---------- */
  // Each painter fills an offscreen canvas of size (cw, ch) and returns anchors for animation.
  function paintStadium(g, cw, ch, P, rand){
    const horizon = ch * 0.40, seats = [];
    const sky = g.createLinearGradient(0, 0, 0, horizon); sky.addColorStop(0, P.sky[0]); sky.addColorStop(.6, P.sky[1]); sky.addColorStop(1, P.sky[2]);
    g.fillStyle = sky; g.fillRect(0, 0, cw, ch);
    if(!P.light) for(let i = 0; i < 90; i++){ g.fillStyle = `rgba(255,255,255,${rand() * .5})`; g.fillRect(rand() * cw, rand() * horizon * .35, 1.2, 1.2) }
    // far stand (two tiers) under a roof; at dusk the bowl is open and the sky shows
    const roofY = P.open ? ch * 0.20 : ch * 0.13, midY = P.open ? ch * 0.29 : ch * 0.255;
    if(P.open){
      const sun = g.createRadialGradient(cw * .7, roofY * .95, 0, cw * .7, roofY * .95, cw * .45);
      sun.addColorStop(0, 'rgba(255,190,120,.85)'); sun.addColorStop(.25, 'rgba(240,120,80,.35)'); sun.addColorStop(1, 'rgba(240,120,80,0)');
      g.fillStyle = sun; g.fillRect(0, 0, cw, horizon);
      for(let i = 0; i < 5; i++){ g.fillStyle = `rgba(40,20,50,${.25 + rand() * .2})`; g.beginPath(); g.ellipse(rand() * cw, roofY * (.2 + rand() * .6), cw * (.12 + rand() * .15), 6 + rand() * 10, 0, 0, 6.283); g.fill() }
    }
    crowd(g, [[0, roofY + 14], [cw, roofY + 14], [cw, midY], [0, midY]], P, rand, .9, () => .55, seats);
    g.fillStyle = P.roof; g.fillRect(0, midY, cw, ch * 0.012);
    for(let x = 0; x < cw; x += 36){ g.fillStyle = `rgba(255,255,255,${P.light ? .25 : .06})`; g.fillRect(x, midY + 2, 22, ch * 0.006) }  // executive boxes
    crowd(g, [[0, midY + ch * 0.012], [cw, midY + ch * 0.012], [cw, horizon - ch * 0.02], [0, horizon - ch * 0.02]], P, rand, .92, () => .72, seats);
    // roof slab with edge lights
    if(P.open){ g.fillStyle = P.roof; g.fillRect(0, roofY - 4, cw, 14) }
    else { g.fillStyle = P.roof; g.beginPath(); g.moveTo(0, 0); g.lineTo(cw, 0); g.lineTo(cw, roofY + 6); g.quadraticCurveTo(cw / 2, roofY + 22, 0, roofY + 6); g.closePath(); g.fill() }
    for(let x = 10; x < cw; x += 24){ const yy = P.open ? roofY + 8 : roofY + 6 + 16 * (1 - Math.pow((x - cw / 2) / (cw / 2), 2)); g.fillStyle = `rgba(255,250,235,${P.light ? .3 : .75})`; g.fillRect(x, yy - 3, 8, 2.4) }
    // LED boards along the far touchline
    const boardY = horizon - ch * 0.02, bh = ch * 0.02;
    const led = g.createLinearGradient(0, 0, cw, 0); led.addColorStop(0, hexA(P.accent, .5)); led.addColorStop(.5, hexA(P.away, .5)); led.addColorStop(1, hexA(P.accent, .5));
    g.fillStyle = led; g.fillRect(0, boardY, cw, bh); g.fillStyle = 'rgba(0,0,0,.35)'; for(let x = 0; x < cw; x += 4) g.fillRect(x, boardY, 1, bh);
    lightPool(g, cw / 2, boardY, cw * .5, P.light ? .0 : .12, hexA(P.accent, 'A').replace(/,A\)$/, ',A)'));
    // pitch in perspective, beyond both edges of the screen
    const cx = cw / 2, base = ch * 1.25;
    // u: -1..1 across the pitch, v: 0 (far touchline) .. 1 (near); wider and lower as it nears the camera
    const pproj = (u, v) => ({x: cx + u * cw * 0.38 * (1 + 2.2 * v), y: horizon + (base - horizon) * Math.pow(v, 1.45)});
    g.save(); g.beginPath(); g.rect(0, horizon, cw, ch - horizon); g.clip();
    g.fillStyle = P.grass[0]; g.fillRect(0, horizon, cw, ch);
    stripes(g, pproj, P, 14);
    markings(g, (u, v) => pproj(u * 0.92, 0.04 + v * 1.0), P, 2);
    // floodlight pools on the grass
    if(!P.light){ lightPool(g, cw * .5, ch * .62, cw * .55, .16, 'rgba(230,255,210,A)'); lightPool(g, cw * .2, ch * .5, cw * .3, .08, 'rgba(255,245,220,A)'); lightPool(g, cw * .8, ch * .5, cw * .3, .08, 'rgba(255,245,220,A)') }
    g.restore();
    // side stands sweeping towards the camera
    crowd(g, [[0, horizon - ch * .02], [cw * .08, horizon], [-cw * .3, ch * 1.1], [0, ch * 1.1]], P, rand, .9, y => .7 + (y - horizon) / ch * 2.2, null);
    crowd(g, [[cw, horizon - ch * .02], [cw * .92, horizon], [cw * 1.3, ch * 1.1], [cw, ch * 1.1]], P, rand, .9, y => .7 + (y - horizon) / ch * 2.2, null);
    // floodlight towers at the roof corners
    const towers = P.open ? [[cw * .08, roofY - 30], [cw * .92, roofY - 30]] : [[cw * .08, roofY * .55], [cw * .92, roofY * .55]];
    towers.forEach(([x, y]) => lampBank(g, x, y, Math.max(.8, cw / 1600), P));
    // haze over the far stand
    const hz = g.createLinearGradient(0, midY, 0, horizon + ch * .08); hz.addColorStop(0, 'rgba(0,0,0,0)'); hz.addColorStop(.7, P.haze); hz.addColorStop(1, 'rgba(0,0,0,0)');
    g.fillStyle = hz; g.fillRect(0, midY, cw, horizon);
    return {seats, towers, horizon};
  }

  function paintAerial(g, cw, ch, P, rand){
    const seats = [], portrait = ch > cw;
    g.fillStyle = P.light ? '#3d4a3a' : '#07090d'; g.fillRect(0, 0, cw, ch);
    // pitch rectangle with a margin, long side along the screen's long side
    const m = Math.min(cw, ch) * 0.13, pw = cw - m * 2, ph = ch - m * 2;
    // crowd around the edges
    crowd(g, [[0, 0], [cw, 0], [cw, m * .8], [0, m * .8]], P, rand, .85, () => .9, seats);
    crowd(g, [[0, ch - m * .8], [cw, ch - m * .8], [cw, ch], [0, ch]], P, rand, .85, () => .9, seats);
    crowd(g, [[0, 0], [m * .8, 0], [m * .8, ch], [0, ch]], P, rand, .85, () => .9, seats);
    crowd(g, [[cw - m * .8, 0], [cw, 0], [cw, ch], [cw - m * .8, ch]], P, rand, .85, () => .9, seats);
    g.fillStyle = P.grass[1]; g.fillRect(m * .8, m * .8, cw - m * 1.6, ch - m * 1.6);
    const n = 16;
    for(let i = 0; i < n; i++){ g.fillStyle = P.grass[i % 2];
      if(portrait) g.fillRect(m * .8, m + ph * i / n, cw - m * 1.6, ph / n + 1); else g.fillRect(m + pw * i / n, m * .8, pw / n + 1, ch - m * 1.6) }
    // diagonal mowing for texture
    g.globalAlpha = .05; g.strokeStyle = '#000'; g.lineWidth = 14;
    for(let k = -ch; k < cw; k += 40){ g.beginPath(); g.moveTo(k, 0); g.lineTo(k + ch, ch); g.stroke() } g.globalAlpha = 1;
    // markings: map u in [-1,1] across, v in [0,1] along
    const proj = portrait ? (u, v) => ({x: cw / 2 + u * pw / 2, y: m + v * ph}) : (u, v) => ({x: m + v * pw, y: ch / 2 + u * ph / 2});
    markings(g, proj, P, Math.max(1.6, Math.min(cw, ch) / 420));
    // four floodlight pools and their towers
    const corners = [[m * .4, m * .4], [cw - m * .4, m * .4], [m * .4, ch - m * .4], [cw - m * .4, ch - m * .4]];
    if(!P.light) corners.forEach(([x, y]) => lightPool(g, x + (cw / 2 - x) * .35, y + (ch / 2 - y) * .35, Math.max(cw, ch) * .45, .09, 'rgba(240,255,225,A)'));
    corners.forEach(([x, y]) => lampBank(g, x, y, Math.max(.6, Math.min(cw, ch) / 1400), P));
    return {seats, towers: corners, horizon: 0};
  }

  function paintGoal(g, cw, ch, P, rand){
    const horizon = ch * 0.42, seats = [];
    const sky = g.createLinearGradient(0, 0, 0, horizon); sky.addColorStop(0, P.sky[0]); sky.addColorStop(1, P.sky[2]);
    g.fillStyle = sky; g.fillRect(0, 0, cw, ch);
    crowd(g, [[0, ch * .08], [cw, ch * .08], [cw, horizon - ch * .015], [0, horizon - ch * .015]], P, rand, .92, y => .5 + (y / horizon) * .5, seats);
    g.fillStyle = P.roof; g.beginPath(); g.moveTo(0, 0); g.lineTo(cw, 0); g.lineTo(cw, ch * .07); g.quadraticCurveTo(cw / 2, ch * .1, 0, ch * .07); g.fill();
    const led = g.createLinearGradient(0, 0, cw, 0); led.addColorStop(0, hexA(P.away, .5)); led.addColorStop(1, hexA(P.accent, .5));
    g.fillStyle = led; g.fillRect(0, horizon - ch * .015, cw, ch * .015);
    // pitch running away from us, seen from just behind the goal line
    const cx = cw / 2, base = ch * 1.05;
    const proj = (u, v) => { const d = 1 - v, k = 0.25 + 0.75 * d; return {x: cx + u * cw * 1.25 * k, y: horizon + (base - horizon) * Math.pow(d, 1.7)} };
    g.save(); g.beginPath(); g.rect(0, horizon, cw, ch); g.clip();
    g.fillStyle = P.grass[0]; g.fillRect(0, horizon, cw, ch);
    stripes(g, proj, P, 18);
    markings(g, (u, v) => proj(u * 0.55, v * 0.98 + 0.02), P, 2.2);
    if(!P.light) lightPool(g, cw / 2, ch * .62, cw * .6, .14, 'rgba(230,255,210,A)');
    g.restore();
    // the net in the foreground: posts, crossbar and a hexagon-ish mesh
    const postW = Math.max(8, cw * .014), left = cw * .1, right = cw * .9, bar = ch * .2;
    g.strokeStyle = P.light ? 'rgba(255,255,255,.6)' : 'rgba(255,255,255,.24)'; g.lineWidth = 1.2;
    const cell = Math.max(18, cw / 48);
    for(let x = -ch; x < cw + ch; x += cell){ g.beginPath(); g.moveTo(x, bar); g.quadraticCurveTo(x + ch * .25, ch * .6, x + ch * .55, ch); g.stroke();
      g.beginPath(); g.moveTo(x, bar); g.quadraticCurveTo(x - ch * .25, ch * .6, x - ch * .55, ch); g.stroke() }
    g.fillStyle = P.light ? '#ffffff' : '#e9edf3';
    g.fillRect(left - postW / 2, bar, postW, ch); g.fillRect(right - postW / 2, bar, postW, ch); g.fillRect(left - postW / 2, bar - postW / 2, right - left + postW, postW);
    g.fillStyle = 'rgba(0,0,0,.25)'; g.fillRect(left + postW / 2, bar + postW / 2, 3, ch); g.fillRect(right + postW / 2, bar + postW / 2, 3, ch);
    const towers = [[cw * .1, ch * .03], [cw * .9, ch * .03]];
    towers.forEach(([x, y]) => lampBank(g, x, y, Math.max(.7, cw / 1700), P));
    return {seats, towers, horizon};
  }

  const PAINTERS = {stadium: paintStadium, dusk: paintStadium, aerial: paintAerial, goal: paintGoal};
  const OVERSCAN = 1.1;   // painted larger than the screen so the camera can drift
  let scene = null, prev = null, fade = 1;

  function build(name){
    const P = palette(name), cw = Math.round(W * OVERSCAN), ch = Math.round(H * OVERSCAN);
    const off = document.createElement('canvas'); off.width = Math.round(cw * dpr); off.height = Math.round(ch * dpr);
    const g = off.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const seed = [...name].reduce((a, c) => a * 31 + c.charCodeAt(0), 7);
    const anchors = PAINTERS[name](g, cw, ch, P, rng(seed));
    // readability: darken (or lighten) towards the content, plus a vignette
    const ov = g.createLinearGradient(0, 0, 0, ch);
    const base = P.light ? '243,245,248' : '6,8,12';
    // extra shade around the horizon, where headings and intro text usually sit
    ov.addColorStop(0, `rgba(${base},${P.overlay[0]})`); ov.addColorStop(.32, `rgba(${base},${P.overlay[0] + .22})`);
    ov.addColorStop(.55, `rgba(${base},${P.overlay[0] + .1})`); ov.addColorStop(1, `rgba(${base},${P.overlay[1]})`);
    g.fillStyle = ov; g.fillRect(0, 0, cw, ch);
    const vg = g.createRadialGradient(cw / 2, ch * .45, Math.min(cw, ch) * .3, cw / 2, ch * .45, Math.max(cw, ch) * .8);
    vg.addColorStop(0, 'rgba(0,0,0,0)'); vg.addColorStop(1, P.light ? 'rgba(255,255,255,.35)' : 'rgba(0,0,0,.55)');
    g.fillStyle = vg; g.fillRect(0, 0, cw, ch);
    return {name, off, cw, ch, P, ...anchors};
  }
  function setScene(name, instant){
    if(!PAINTERS[name]) name = 'stadium';
    if(scene && scene.name === name && scene.cw === Math.round(W * OVERSCAN) && scene.P.light === isLight()) return;
    prev = instant ? null : scene; scene = build(name); fade = prev ? 0 : 1;
    if(!running) frame(performance.now(), true);
  }

  function resize(){
    dpr = Math.min(1.5, devicePixelRatio || 1);
    W = innerWidth; H = innerHeight;
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    scene = null; setScene(sceneFor(), true);
  }

  /* ---------- Animated layers ---------- */
  function blit(s, t, alpha){
    // slow camera drift (Ken Burns) plus parallax from cursor and scroll
    const z = 1 + 0.025 * Math.sin(t / 21000);
    const dx = (s.cw - W) / 2 + (mouse.x - 0.5) * -14 + Math.sin(t / 26000) * 8;
    const dy = (s.ch - H) / 2 + (mouse.y - 0.5) * -10 + Math.min(scrollY * 0.04, (s.ch - H) / 2);
    ctx.globalAlpha = alpha;
    ctx.drawImage(s.off, 0, 0, s.off.width, s.off.height, -dx * z - (W * (z - 1)) / 2, -dy * z - (H * (z - 1)) / 2, s.cw * z, s.ch * z);
    ctx.globalAlpha = 1;
  }
  function beams(s, t){
    if(!s.P.beam || !s.towers) return;
    ctx.globalCompositeOperation = 'screen';
    s.towers.forEach(([x, y], i) => {
      const sx = x - (s.cw - W) / 2, sy = y - (s.ch - H) / 2;
      const target = Math.atan2(H * .75 - sy, W / 2 - sx) + Math.sin(t * 0.00012 + i * 1.9) * 0.08;
      const len = Math.hypot(W, H), spread = 0.2;
      const gr = ctx.createRadialGradient(sx, sy, 0, sx, sy, len);
      const a = 0.07 * s.P.beam * (0.85 + 0.15 * Math.sin(t * 0.0009 + i));
      gr.addColorStop(0, `rgba(255,248,228,${a})`); gr.addColorStop(.6, `rgba(255,248,228,${a * .3})`); gr.addColorStop(1, 'rgba(255,248,228,0)');
      ctx.fillStyle = gr; ctx.beginPath(); ctx.moveTo(sx, sy);
      ctx.lineTo(sx + Math.cos(target - spread) * len, sy + Math.sin(target - spread) * len);
      ctx.lineTo(sx + Math.cos(target + spread) * len, sy + Math.sin(target + spread) * len); ctx.closePath(); ctx.fill();
    });
    ctx.globalCompositeOperation = 'source-over';
  }
  function crowdFlashes(s, dt){
    if(s.P.light || !s.seats || !s.seats.length) return;
    if(Math.random() < 0.08 * dt && flashes.length < 6){ const p = s.seats[Math.floor(Math.random() * s.seats.length)]; flashes.push({x: p[0], y: p[1], s: p[2], life: 10 + Math.random() * 8}) }
    flashes = flashes.filter(f => (f.life -= dt) > 0);
    for(const f of flashes){
      const x = f.x * W * OVERSCAN - (s.cw - W) / 2, y = f.y * H * OVERSCAN - (s.ch - H) / 2, a = Math.min(1, f.life / 6) * .9;
      const gr = ctx.createRadialGradient(x, y, 0, x, y, 9 * f.s + 4); gr.addColorStop(0, `rgba(255,255,255,${a})`); gr.addColorStop(1, 'rgba(255,255,255,0)');
      ctx.fillStyle = gr; ctx.fillRect(x - 14, y - 14, 28, 28);
    }
  }
  function ball(s, dt){
    if(Math.random() < 0.004 * dt && comets.length < 1){
      const fromLeft = Math.random() < 0.5, y0 = H * (0.55 + Math.random() * 0.3);
      comets.push({x0: fromLeft ? -30 : W + 30, y0, x1: fromLeft ? W + 30 : -30, y1: y0 + (Math.random() - .5) * H * .2, h: 90 + Math.random() * 160, t: 0, dur: 2200 + Math.random() * 900});
    }
    comets = comets.filter(c => (c.t += dt * 16.7) < c.dur);
    for(const c of comets){
      const k = c.t / c.dur, x = c.x0 + (c.x1 - c.x0) * k, ground = c.y0 + (c.y1 - c.y0) * k, lift = Math.sin(k * Math.PI) * c.h;
      ctx.fillStyle = 'rgba(0,0,0,.28)'; ctx.beginPath(); ctx.ellipse(x, ground, 7 - lift / 40, 2.4, 0, 0, 6.283); ctx.fill();   // shadow
      for(let i = 8; i >= 0; i--){ const u = Math.max(0, k - i * 0.004), xx = c.x0 + (c.x1 - c.x0) * u, yy = c.y0 + (c.y1 - c.y0) * u - Math.sin(u * Math.PI) * c.h;
        ctx.fillStyle = `rgba(255,255,255,${(1 - i / 8) * (i ? .25 : .95)})`; ctx.beginPath(); ctx.arc(xx, yy, i ? 3 : 4.2, 0, 6.283); ctx.fill() }
    }
  }
  function sparks(dt){
    bursts = bursts.filter(b => (b.life -= dt) > 0);
    for(const b of bursts){ b.x += b.vx * dt; b.y += b.vy * dt; b.vy += 0.04 * dt; b.vx *= 0.985; ctx.fillStyle = hexA(b.col, Math.min(1, b.life / 30)); ctx.beginPath(); ctx.arc(b.x, b.y, b.r, 0, 6.283); ctx.fill() }
  }

  function frame(now, still){
    if(running && !still){ skip = !skip; if(skip){ requestAnimationFrame(f => frame(f)); return } }   // ~30 fps
    const dt = Math.min(4, (now - last) / 16.7 || 1); last = now;
    mouse.x += (mouse.tx - mouse.x) * 0.05; mouse.y += (mouse.ty - mouse.y) * 0.05;
    const t = still ? 0 : now - t0;
    if(!scene) return;
    ctx.fillStyle = scene.P.bg; ctx.fillRect(0, 0, W, H);
    if(prev && fade < 1){ blit(prev, t, 1); fade = Math.min(1, fade + (still ? 1 : 0.06 * dt)); blit(scene, t, fade); if(fade >= 1) prev = null }
    else blit(scene, t, 1);
    beams(scene, t);
    if(!still) sparks(dt);           // calm by design: no flying ball or crowd flashes behind content
    if(running) requestAnimationFrame(f => frame(f));
  }
  function start(){ if(running || !enabled || reduced.matches || document.hidden) return; running = true; last = performance.now(); requestAnimationFrame(f => frame(f)) }
  function stop(){ running = false }
  function sync(){ (enabled && !reduced.matches && !document.hidden) ? start() : (stop(), frame(performance.now(), true)) }

  addEventListener('resize', () => { clearTimeout(resize.t); resize.t = setTimeout(resize, 150) });
  addEventListener('pointermove', e => { mouse.tx = e.clientX / W; mouse.ty = e.clientY / H }, {passive: true});
  addEventListener('scroll', () => { scrollY = window.scrollY }, {passive: true});
  addEventListener('hashchange', () => setScene(sceneFor()));
  document.addEventListener('visibilitychange', sync);
  reduced.addEventListener('change', sync);
  // Repaint when the theme changes.
  const repaint = () => { if(scene){ const n = scene.name; scene = null; setScene(n, true) } };
  new MutationObserver(repaint).observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme']});
  matchMedia('(prefers-color-scheme: light)').addEventListener('change', repaint);

  window.LivingPitch = {
    burst(x, y, colors){
      if(!running) return;
      const cols = colors && colors.length ? colors : [scene ? scene.P.accent : '#c2f25e', scene ? scene.P.away : '#74bdfc'];
      for(let i = 0; i < 70; i++){ const a = Math.random() * Math.PI * 2, s = 1 + Math.random() * 4.5;
        bursts.push({x, y, vx: Math.cos(a) * s, vy: Math.sin(a) * s - 1.5, r: 1.2 + Math.random() * 2.4, life: 50 + Math.random() * 50, col: cols[i % cols.length]}) }
    },
    setEnabled(on){ enabled = on; store.set('fx', on ? 'on' : 'off'); sync() },
    setScene(name){ setScene(name) },
    get enabled(){ return enabled },
    get scene(){ return scene && scene.name },
  };
  const boot = () => { resize(); sync() };
  document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', boot) : boot();

  // Spotlight: cards light up where the cursor is (CSS reads --mx/--my).
  addEventListener('pointermove', e => {
    const card = e.target.closest && e.target.closest('.card, .stat, .fx, .board');
    if(!card) return;
    const r = card.getBoundingClientRect();
    card.style.setProperty('--mx', (e.clientX - r.left) + 'px'); card.style.setProperty('--my', (e.clientY - r.top) + 'px');
  }, {passive: true});
})();
