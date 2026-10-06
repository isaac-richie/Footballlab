(function(){
  'use strict';
  const K = window.Kickabout, Net = window.KickNet;
  const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
  const store = {get(k){ try{ return localStorage.getItem(k) }catch{ return null } }, set(k, v){ try{ localStorage.setItem(k, v) }catch{} }};
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v)), lerp = (a, b, t) => a + (b - a) * t;
  const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
  const esc = s => String(s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const KIT = {home: '#c2f25e', homeInk: '#13200a', away: '#74bdfc', awayInk: '#0b1b2b', gk0: '#f2b45e', gk1: '#e05a8a'};

  /* ---------------- State ---------------- */
  const S = {role: null, mode: store.get('ka-mode') || '5v5', minutes: +(store.get('ka-mins') || 3), match: null, link: null, room: null,
    names: ['You', 'CPU'], flip: false, portrait: false, cam: {x: 0, y: 0}, snaps: [], remote: {}, evBuf: [], acc: 0, last: 0,
    sendT: 0, inT: 0, running: false, ended: false, chatT: 0, startInfo: null};
  const input = {mx: 0, my: 0, pass: 0, shoot: 0, power: 0.6, aimY: 0, tackle: 0, switch: 0};
  const myId = () => S.role === 'guest' ? 'p1' : 'p0';

  /* ---------------- Canvas + view ---------------- */
  const canvas = $('#field'), ctx = canvas.getContext('2d');
  let LW = 960, LH = 600, dpr = 1;
  function layout(){
    const cssW = canvas.parentElement.clientWidth || 960;
    S.portrait = cssW < 640 && innerHeight > innerWidth;
    LW = S.portrait ? 600 : 960; LH = S.portrait ? 880 : 600;
    dpr = Math.min(2, devicePixelRatio || 1);
    canvas.width = LW * dpr; canvas.height = LH * dpr;
  }
  addEventListener('resize', layout); layout();
  function viewScale(m){
    const along = S.portrait ? LH : LW, across = S.portrait ? LW : LH;
    if(m.mode === '11v11') return S.portrait ? across / 40 : along / 56;
    return Math.min(along / (m.w + 7), across / (m.h + 6));
  }
  // World -> screen matrix: flip (guest sees their attack going right/up), then rotate for portrait.
  function matrix(m){
    const s = viewScale(m), F = S.flip ? -1 : 1;
    const [a, b, c, d] = S.portrait ? [0, -s * F, s * F, 0] : [s * F, 0, 0, s * F];
    const e = LW / 2 - (a * S.cam.x + c * S.cam.y), f = LH / 2 - (b * S.cam.x + d * S.cam.y);
    return {a, b, c, d, e, f, s};
  }
  const toScreen = (M, x, y) => ({x: M.a * x + M.c * y + M.e, y: M.b * x + M.d * y + M.f});
  // Screen direction (right, down) -> world direction.
  function toWorldDir(jx, jy){
    let x = S.portrait ? -jy : jx, y = S.portrait ? jx : jy;
    if(S.flip){ x = -x; y = -y }
    return {x, y};
  }

  /* ---------------- Sound ---------------- */
  let audio = null, soundOn = store.get('ka-sound') !== 'off';
  const paintSound = () => { $('#sound').textContent = soundOn ? '🔊' : '🔇' };
  paintSound(); $('#sound').onclick = () => { soundOn = !soundOn; store.set('ka-sound', soundOn ? 'on' : 'off'); paintSound() };
  const ac = () => { if(!audio){ try{ audio = new (window.AudioContext || window.webkitAudioContext)() }catch{} } if(audio && audio.state === 'suspended') audio.resume(); return audio };
  function noise(dur, type, freq, peak){ const a = ac(); if(!a || !soundOn) return; const n = Math.floor(a.sampleRate * dur), buf = a.createBuffer(1, n, a.sampleRate), d = buf.getChannelData(0); for(let i = 0; i < n; i++) d[i] = Math.random() * 2 - 1;
    const s = a.createBufferSource(), f = a.createBiquadFilter(), g = a.createGain(), t = a.currentTime; s.buffer = buf; f.type = type; f.frequency.value = freq;
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(peak, t + Math.min(0.2, dur * 0.2)); g.gain.exponentialRampToValueAtTime(0.0001, t + dur); s.connect(f).connect(g).connect(a.destination); s.start(t); s.stop(t + dur) }
  function tone(freq, dur, peak, type = 'sine', vib = 0){ const a = ac(); if(!a || !soundOn) return; const o = a.createOscillator(), g = a.createGain(), t = a.currentTime; o.type = type; o.frequency.value = freq;
    if(vib){ const l = a.createOscillator(), lg = a.createGain(); l.frequency.value = 28; lg.gain.value = vib; l.connect(lg).connect(o.frequency); l.start(t); l.stop(t + dur) }
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(peak, t + 0.01); g.gain.exponentialRampToValueAtTime(0.0001, t + dur); o.connect(g).connect(a.destination); o.start(t); o.stop(t + dur + 0.02) }
  const sfx = {kick: () => { tone(110, 0.1, 0.35); noise(0.05, 'lowpass', 600, 0.2) }, shot: () => { tone(80, 0.18, 0.5); noise(0.08, 'lowpass', 500, 0.35) },
    whistle: () => tone(2900, 0.35, 0.1, 'sine', 140), cheer: () => noise(2.2, 'bandpass', 1100, 0.22), save: () => noise(0.9, 'bandpass', 700, 0.12), thud: () => tone(70, 0.08, 0.3, 'triangle')};

  /* ---------------- Input ---------------- */
  const keys = new Set();
  const typing = () => document.activeElement && /input|textarea/i.test(document.activeElement.tagName);
  let shootDownAt = 0, padShoot = false;
  function press(b){ if(b === 'shoot'){ if(!shootDownAt) shootDownAt = performance.now() } else input[b]++ }
  function release(b){ if(b === 'shoot' && shootDownAt){ input.power = clamp((performance.now() - shootDownAt) / 900, 0.15, 1); input.aimY = clamp(input.my, -1, 1); input.shoot++; shootDownAt = 0 } }
  const KEYMAP = {j: 'pass', x: 'pass', k: 'shoot', ' ': 'shoot', l: 'tackle', c: 'tackle', shift: 'switch', q: 'switch'};
  addEventListener('keydown', e => {
    if(typing()) return;
    const k = e.key.toLowerCase();
    if(['arrowup', 'arrowdown', 'arrowleft', 'arrowright', ' ', 'w', 'a', 's', 'd'].includes(k) && S.running) e.preventDefault();
    if(e.repeat) return;
    keys.add(k); if(KEYMAP[k] && S.running) press(KEYMAP[k]);
  });
  addEventListener('keyup', e => { const k = e.key.toLowerCase(); keys.delete(k); if(KEYMAP[k]) release(KEYMAP[k]) });
  addEventListener('blur', () => keys.clear());
  // Touch: floating joystick on the left of the pitch, buttons on the right.
  const pad = $('#pad'), stick = $('#stick'), knob = stick.querySelector('i');
  let stickId = null, stickO = null, stickV = {x: 0, y: 0};
  const isTouch = matchMedia('(pointer: coarse)').matches || 'ontouchstart' in window;
  if(isTouch){ pad.classList.add('on'); $('#btns').hidden = false; $('#help').textContent = 'Drag on the left of the pitch to move. Hold SHOOT for power; aim with the stick as you release.' }
  pad.addEventListener('pointerdown', e => {
    if(e.target.closest('.btns') || stickId !== null || !S.running) return;
    const r = pad.getBoundingClientRect(); if(e.clientX - r.left > r.width * 0.6) return;
    stickId = e.pointerId; stickO = {x: e.clientX, y: e.clientY}; stick.style.left = (e.clientX - r.left) + 'px'; stick.style.top = (e.clientY - r.top) + 'px'; stick.style.display = 'block';
    try{ pad.setPointerCapture(e.pointerId) }catch{}
  });
  pad.addEventListener('pointermove', e => {
    if(e.pointerId !== stickId) return;
    const dx = e.clientX - stickO.x, dy = e.clientY - stickO.y, d = Math.hypot(dx, dy), max = 50, k = d > max ? max / d : 1;
    stickV = {x: dx * k / max, y: dy * k / max}; knob.style.transform = `translate(${dx * k}px,${dy * k}px)`;
  });
  const endStick = e => { if(e.pointerId !== stickId) return; stickId = null; stickV = {x: 0, y: 0}; stick.style.display = 'none'; knob.style.transform = '' };
  pad.addEventListener('pointerup', endStick); pad.addEventListener('pointercancel', endStick);
  $$('#btns button').forEach(b => {
    b.addEventListener('pointerdown', e => { e.preventDefault(); ac(); press(b.dataset.b) });
    b.addEventListener('pointerup', () => release(b.dataset.b)); b.addEventListener('pointerleave', () => release(b.dataset.b));
  });
  // Gamepad: A pass, B/RT shoot (hold), X tackle, LB/RB switch.
  let gpPrev = {};
  function pollGamepad(){
    const gp = (navigator.getGamepads ? [...navigator.getGamepads()] : []).find(Boolean); if(!gp) return null;
    const btn = i => gp.buttons[i] && gp.buttons[i].pressed, map = {pass: btn(0), shoot: btn(1) || btn(7), tackle: btn(2), switch: btn(4) || btn(5)};
    for(const [k, on] of Object.entries(map)){ if(on && !gpPrev[k]) press(k); if(!on && gpPrev[k]) release(k) }
    gpPrev = map;
    const ax = gp.axes[0] || 0, ay = gp.axes[1] || 0; return Math.hypot(ax, ay) > 0.2 ? {x: ax, y: ay} : {x: 0, y: 0};
  }
  function readMove(){
    let jx = (keys.has('d') || keys.has('arrowright') ? 1 : 0) - (keys.has('a') || keys.has('arrowleft') ? 1 : 0);
    let jy = (keys.has('s') || keys.has('arrowdown') ? 1 : 0) - (keys.has('w') || keys.has('arrowup') ? 1 : 0);
    const gp = pollGamepad();
    if(gp && (gp.x || gp.y)){ jx = gp.x; jy = gp.y }
    if(stickV.x || stickV.y){ jx = stickV.x; jy = stickV.y }
    const w = toWorldDir(jx, jy); input.mx = w.x; input.my = w.y;
  }
  const myTeam = () => S.role === 'guest' ? 1 : 0;

  /* ---------------- Match control ---------------- */
  function startLocal(seed){
    S.match = K.newMatch({mode: S.mode, minutes: S.minutes, seed});
    K.join(S.match, 'p0', 0);
    if(S.role === 'host') K.join(S.match, 'p1', 1);
    S.flip = false; S.ended = false; S.running = true; S.acc = 0; S.last = performance.now(); S.evBuf = [];
    hideOverlays(); hud(view()); ac(); sfx.whistle();
  }
  function startGuest(info){
    S.startInfo = info; S.mode = info.mode; S.minutes = info.minutes; S.names = info.names; S.flip = true;
    S.snaps = []; S.ended = false; S.running = true; hideOverlays(); setNames(); ac(); sfx.whistle();
  }
  function hideOverlays(){ for(const id of ['#lobby', '#room', '#final']) $(id).hidden = true }
  function setNames(){
    const mine = S.role === 'guest' ? 1 : 0;
    $('#n-home').textContent = S.names[0] + (mine === 0 ? ' (you)' : ''); $('#n-away').textContent = S.names[1] + (mine === 1 ? ' (you)' : '');
  }

  // Unified view model for drawing, built from the live match (host/CPU) or from snapshots (guest).
  function view(){
    if(S.role !== 'guest'){
      const m = S.match; if(!m) return null;
      return {mode: m.mode, w: m.w, h: m.h, goal: m.goal, t: m.t, duration: m.duration, phase: m.phase, score: m.score,
        players: m.players.map(p => ({x: p.x, y: p.y, dir: p.dir, team: p.team, gk: p.gk, ctrl: p.ctrl, stun: p.stun > 0, slot: p.slot})), ball: {x: m.ball.x, y: m.ball.y, owner: m.ball.owner}};
    }
    if(S.snaps.length === 0 || !S.startInfo) return null;
    const cfg = K.MODES[S.mode], renderT = performance.now() - 110;
    let a = S.snaps[0], b = S.snaps[S.snaps.length - 1];
    for(let i = S.snaps.length - 1; i > 0; i--) if(S.snaps[i - 1].at <= renderT){ a = S.snaps[i - 1]; b = S.snaps[i]; break }
    const k = b.at === a.at ? 1 : clamp((renderT - a.at) / (b.at - a.at), 0, 1), A = a.s, B = b.s;
    const n = cfg.slots.length;
    return {mode: S.mode, w: cfg.w, h: cfg.h, goal: cfg.goal, t: lerp(A.t, B.t, k), duration: S.minutes * 60, phase: B.ph, score: B.sc,
      players: B.p.map((q, i) => ({x: lerp(A.p[i][0], q[0], k), y: lerp(A.p[i][1], q[1], k), dir: q[2], team: i < n ? 0 : 1, gk: i % n === 0, ctrl: q[3], stun: !!q[4], slot: i % n})),
      ball: {x: lerp(A.b[0], B.b[0], k), y: lerp(A.b[1], B.b[1], k), owner: B.b[2]}};
  }

  // Simulation and networking run on a timer, not the drawing loop, so a host who switches
  // tabs keeps the match going (background timers are slowed, and the host catches up).
  function tick(){
    if(!S.running) return;
    const now = performance.now();
    readMove();
    if(S.role === 'guest'){
      if(now - S.inT > 33 && S.link){ S.link.send('game', {k: 'in', i: input}); S.inT = now }
      return;
    }
    if(!S.match) return;
    S.acc += Math.min(document.hidden ? 1.5 : 0.25, (now - S.last) / 1000); S.last = now;
    while(S.acc >= K.DT){
      const inputs = {p0: input}; if(S.role === 'host') inputs.p1 = S.remote;
      K.step(S.match, inputs); S.acc -= K.DT;
      for(const e of S.match.events){ S.evBuf.push(e); effect(e) }
      if(S.match.phase === 'end' && !S.ended){ finish(); break }
    }
    if(S.role === 'host' && S.link && now - S.sendT > 50){ const snap = K.snapshot(S.match); snap.ev = S.evBuf.slice(-40); S.evBuf = []; S.link.send('game', {k: 'st', s: snap}); S.sendT = now }
  }
  setInterval(tick, 1000 / 60);
  function frame(now){
    const v = view(); if(v){ draw(v, now); hud(v) } else drawIdle(now);
    requestAnimationFrame(frame);
  }
  function effect(e){
    if(e.type === 'pass') sfx.kick(); else if(e.type === 'shot') sfx.shot(); else if(e.type === 'tackle') sfx.thud(); else if(e.type === 'save') sfx.save();
    else if(e.type === 'whistle') sfx.whistle();
    else if(e.type === 'goal'){
      sfx.cheer(); const mine = e.team === myTeam();
      flash(mine ? 'GOAL!' : 'Goal', mine ? '#c2f25e' : '#ffffff'); if(!reduced()) S.shake = 10;
    } else if(e.type === 'fulltime'){ sfx.whistle(); setTimeout(() => sfx.whistle(), 400) }
  }
  function flash(text, color){ const f = $('#flash'); f.textContent = text; f.style.color = color; f.classList.remove('on'); void f.offsetWidth; f.classList.add('on') }
  function hud(v){
    $('#score').textContent = `${v.score[0]} - ${v.score[1]}`;
    const left = Math.max(0, v.duration - v.t); $('#clock').textContent = v.phase === 'end' ? 'Full time' : `${Math.floor(left / 60)}:${String(Math.floor(left % 60)).padStart(2, '0')}`;
  }
  function finish(){
    S.ended = true; S.running = false;
    const sc = S.match ? S.match.score : S.lastScore || [0, 0], me = myTeam(), them = 1 - me;
    if(S.role === 'host' && S.link) S.link.send('chat', {k: 'end', score: sc});
    const res = sc[me] > sc[them] ? 'You win!' : sc[me] < sc[them] ? 'You lost' : 'Draw';
    $('#final-title').textContent = res; $('#final-text').textContent = `${S.names[0]} ${sc[0]} - ${sc[1]} ${S.names[1]} · ${S.mode} · ${S.minutes} min`;
    const text = `Kickabout ${S.mode}: ${S.names[0]} ${sc[0]}-${sc[1]} ${S.names[1]} ⚽ Play: ${location.href.split(/[?#]/)[0]}`;
    $('#final-share').href = 'https://wa.me/?text=' + encodeURIComponent(text);
    $('#again').textContent = S.role === 'guest' ? 'Ask for a rematch' : 'Rematch';
    setTimeout(() => { $('#final').hidden = false }, 1200);
  }

  /* ---------------- Drawing ---------------- */
  function drawIdle(now){
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.fillStyle = '#1d5a33'; ctx.fillRect(0, 0, LW, LH);
    drawPitch({mode: S.mode, ...K.MODES[S.mode]}, now);
  }
  function drawPitch(v){
    const M = matrix(v), w = v.w, h = v.h;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.fillStyle = '#163f27'; ctx.fillRect(0, 0, LW, LH);
    ctx.setTransform(M.a * dpr, M.b * dpr, M.c * dpr, M.d * dpr, M.e * dpr, M.f * dpr);
    // Boards around the pitch (it's a cage: the ball rebounds).
    ctx.fillStyle = '#0d1b13'; ctx.fillRect(-w / 2 - 2.4, -h / 2 - 2.4, w + 4.8, h + 4.8);
    const stripes = 12;
    for(let i = 0; i < stripes; i++){ ctx.fillStyle = i % 2 ? '#2f7d43' : '#348a4a'; ctx.fillRect(-w / 2 + i * w / stripes, -h / 2, w / stripes + 0.02, h) }
    ctx.strokeStyle = '#ffffffd9'; ctx.lineWidth = Math.max(0.12, 1.6 / M.s);
    ctx.strokeRect(-w / 2, -h / 2, w, h);
    ctx.beginPath(); ctx.moveTo(0, -h / 2); ctx.lineTo(0, h / 2); ctx.stroke();
    ctx.beginPath(); ctx.arc(0, 0, v.mode === '11v11' ? 9.15 : h * 0.16, 0, 6.283); ctx.stroke();
    const boxD = v.mode === '11v11' ? 16.5 : w * 0.14, boxW = v.mode === '11v11' ? 40.3 : v.goal * 2.8, smallD = v.mode === '11v11' ? 5.5 : w * 0.05, smallW = v.mode === '11v11' ? 18.3 : v.goal * 1.6;
    for(const s of [-1, 1]){
      ctx.strokeRect(s > 0 ? w / 2 - boxD : -w / 2, -boxW / 2, boxD, boxW);
      ctx.strokeRect(s > 0 ? w / 2 - smallD : -w / 2, -smallW / 2, smallD, smallW);
      // Goal with a net
      const gx = s * w / 2, depth = Math.min(2, v.goal * 0.4);
      ctx.fillStyle = '#ffffff1f'; ctx.fillRect(s > 0 ? gx : gx - depth, -v.goal / 2, depth, v.goal);
      ctx.save(); ctx.strokeStyle = '#ffffff40'; ctx.lineWidth = Math.max(0.04, 0.6 / M.s);
      for(let y = -v.goal / 2; y <= v.goal / 2 + 0.01; y += v.goal / 8){ ctx.beginPath(); ctx.moveTo(gx, y); ctx.lineTo(gx + s * depth, y); ctx.stroke() }
      ctx.restore();
      ctx.strokeStyle = '#ffffff'; ctx.lineWidth = Math.max(0.18, 2.4 / M.s); ctx.strokeRect(s > 0 ? gx : gx - depth, -v.goal / 2, depth, v.goal);
      ctx.strokeStyle = '#ffffffd9'; ctx.lineWidth = Math.max(0.12, 1.6 / M.s);
    }
    return M;
  }
  function draw(v, now){
    // Camera: small pitches fit on screen; 11 v 11 follows the ball.
    if(v.mode === '11v11'){ S.cam.x = lerp(S.cam.x, clamp(v.ball.x, -v.w / 2 + 18, v.w / 2 - 18), 0.08); S.cam.y = lerp(S.cam.y, clamp(v.ball.y, -v.h / 2 + 10, v.h / 2 - 10), 0.08) }
    else S.cam = {x: 0, y: 0};
    const M = drawPitch(v);
    if(S.shake > 0.3){ ctx.translate((Math.random() - 0.5) * S.shake / M.s, (Math.random() - 0.5) * S.shake / M.s); S.shake *= 0.85 }
    const me = myId();
    // Ball shadow first, then players, then ball.
    ctx.fillStyle = '#0005'; ctx.beginPath(); ctx.ellipse(v.ball.x + 0.15, v.ball.y + 0.15, Math.max(0.3, 4 / M.s), Math.max(0.22, 3 / M.s), 0, 0, 6.283); ctx.fill();
    const R = Math.max(0.62, 11 / M.s), BR = Math.max(0.36, 5 / M.s);   // never smaller than ~11px / 5px on screen
    for(const p of v.players){
      const colour = p.gk ? (p.team ? KIT.gk1 : KIT.gk0) : p.team ? KIT.away : KIT.home;
      ctx.fillStyle = '#0006'; ctx.beginPath(); ctx.arc(p.x + R * 0.22, p.y + R * 0.22, R, 0, 6.283); ctx.fill();
      if(p.ctrl){ ctx.strokeStyle = p.ctrl === me ? '#ffffff' : '#ffd166'; ctx.lineWidth = Math.max(0.12, 2 / M.s); ctx.beginPath(); ctx.arc(p.x, p.y, R * 1.55 + Math.sin(now / 180) * R * 0.1, 0, 6.283); ctx.stroke() }
      ctx.fillStyle = p.stun ? '#8a96a8' : colour; ctx.beginPath(); ctx.arc(p.x, p.y, R, 0, 6.283); ctx.fill();
      ctx.strokeStyle = '#0008'; ctx.lineWidth = Math.max(0.06, 1 / M.s); ctx.stroke();
      ctx.strokeStyle = '#ffffffcc'; ctx.lineWidth = Math.max(0.1, 1.6 / M.s); ctx.beginPath(); ctx.moveTo(p.x + Math.cos(p.dir) * R * 0.5, p.y + Math.sin(p.dir) * R * 0.5); ctx.lineTo(p.x + Math.cos(p.dir) * R * 1.35, p.y + Math.sin(p.dir) * R * 1.35); ctx.stroke();
    }
    ctx.fillStyle = '#ffffff'; ctx.beginPath(); ctx.arc(v.ball.x, v.ball.y, BR, 0, 6.283); ctx.fill(); ctx.strokeStyle = '#1c2430'; ctx.lineWidth = Math.max(0.05, 0.8 / M.s); ctx.stroke();
    // Screen-space labels (never mirrored or rotated)
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    const numSize = clamp(M.s * 0.7, 10, 15), Rpx = Math.max(0.62 * M.s, 11);
    v.players.forEach((p, i) => {
      const q = toScreen(M, p.x, p.y), ink = p.gk ? '#1b1206' : p.team ? KIT.awayInk : KIT.homeInk;
      ctx.font = `800 ${numSize}px -apple-system,Inter,sans-serif`; ctx.fillStyle = ink; ctx.fillText(p.gk ? '1' : String(p.slot + 1), q.x, q.y + 0.5);
      if(p.ctrl){ ctx.font = '700 12px -apple-system,Inter,sans-serif'; ctx.fillStyle = '#fff'; ctx.strokeStyle = '#000b'; ctx.lineWidth = 3;
        const label = p.ctrl === me ? 'YOU' : S.names[p.team] || ''; ctx.strokeText(label, q.x, q.y - Rpx * 1.6 - 8); ctx.fillText(label, q.x, q.y - Rpx * 1.6 - 8) }
    });
    // Shot power meter beside my player
    if(shootDownAt){ const mine = v.players.find(p => p.ctrl === me); if(mine){ const q = toScreen(M, mine.x, mine.y), pw = clamp((performance.now() - shootDownAt) / 900, 0, 1);
      ctx.fillStyle = '#000a'; ctx.fillRect(q.x - 22, q.y + 1.3 * M.s, 44, 7); ctx.fillStyle = pw > 0.85 ? '#f07272' : '#c2f25e'; ctx.fillRect(q.x - 22, q.y + 1.3 * M.s, 44 * pw, 7) } }
    if(v.mode === '11v11') minimap(v);
    if(v.phase === 'kickoff'){ ctx.font = '800 22px -apple-system,Inter,sans-serif'; ctx.fillStyle = '#ffffffd9'; ctx.fillText('Kick off', LW / 2, 40) }
  }
  function minimap(v){
    const mw = S.portrait ? 90 : 150, mh = mw * v.h / v.w, x0 = LW - mw - 12, y0 = 12;
    ctx.fillStyle = '#0b0f14b3'; ctx.fillRect(x0 - 4, y0 - 4, mw + 8, mh + 8);
    ctx.strokeStyle = '#ffffff55'; ctx.lineWidth = 1; ctx.strokeRect(x0, y0, mw, mh);
    const F = S.flip ? -1 : 1, pt = (x, y) => ({x: x0 + (F * x / v.w + 0.5) * mw, y: y0 + (F * y / v.h + 0.5) * mh});
    for(const p of v.players){ const q = pt(p.x, p.y); ctx.fillStyle = p.team ? KIT.away : KIT.home; ctx.fillRect(q.x - 1.5, q.y - 1.5, 3, 3) }
    const b = pt(v.ball.x, v.ball.y); ctx.fillStyle = '#fff'; ctx.beginPath(); ctx.arc(b.x, b.y, 2.5, 0, 6.283); ctx.fill();
  }

  /* ---------------- Lobby + online ---------------- */
  const nameIn = $('#name'); nameIn.value = store.get('ka-name') || '';
  const myName = () => (nameIn.value.trim() || 'Player').slice(0, 16);
  nameIn.oninput = () => store.set('ka-name', nameIn.value.trim());
  function seg(id, key, val){ $$(`#${id} button`).forEach(b => { b.setAttribute('aria-pressed', String(b.dataset.v === String(val))); b.onclick = () => { S[key] = key === 'minutes' ? +b.dataset.v : b.dataset.v; store.set(key === 'minutes' ? 'ka-mins' : 'ka-mode', b.dataset.v); seg(id, key, S[key]); if(!S.running) drawIdle(0) } }) }
  seg('mode', 'mode', S.mode); seg('mins', 'minutes', S.minutes);

  $('#vs-cpu').onclick = () => { S.role = 'cpu'; S.names = [myName(), 'CPU']; setNames(); $('#chat').hidden = true; $('#layout').classList.add('solo'); startLocal((Math.random() * 2 ** 32) >>> 0) };
  $('#host').onclick = () => openRoom('host', Net.roomCode());
  $('#join').onclick = () => { const code = $('#code-in').value.trim().toUpperCase(); if(/^[A-Z0-9]{6}$/.test(code)) openRoom('guest', code); else $('#code-in').focus() };

  function openRoom(role, code){
    ac(); S.role = role; S.room = code;
    $('#lobby').hidden = true; $('#room').hidden = false;
    const link = location.href.split(/[?#]/)[0] + '?room=' + code;
    $('#room-code').textContent = code;
    $('#room-title').textContent = role === 'host' ? 'Room ready' : 'Joining room';
    $('#room-text').textContent = role === 'host' ? 'Send this code or link to a friend.' : 'Connecting to your friend…';
    $('#copy-link').onclick = async () => { try{ await navigator.clipboard.writeText(link); $('#copy-link').textContent = 'Copied!' }catch{ prompt('Copy this link', link) } };
    $('#wa-link').href = 'https://wa.me/?text=' + encodeURIComponent(`Fancy a ${S.mode} Kickabout? Join me: ${link}`);
    $('#start-online').hidden = role !== 'host'; $('#start-online').disabled = true;
    S.link = Net.connect(code, role, {name: myName(), status: onStatus});
    S.link.on('game', onGame); S.link.on('chat', onChat);
  }
  function onStatus(status, link){
    const el = $('#room-status');
    const text = {waiting: 'Waiting for a friend…', joining: 'Looking for the room…', connecting: `Connecting to ${link.peer || 'your friend'}…`,
      connected: `${link.peer || 'Friend'} is here · ${link.via === 'p2p' ? 'direct connection' : 'relayed connection'}`, full: 'That room is full.', left: `${link.peer || 'Your friend'} left.`, lost: 'Connection lost.'}[status] || status;
    el.className = 'pill-status' + (status === 'connected' ? ' ok' : ''); el.innerHTML = `<i></i>${esc(text)}`;
    if(status === 'connected'){
      $('#start-online').disabled = false; $('#chat').hidden = false; $('#layout').classList.remove('solo');
      $('#peer-name').textContent = 'with ' + (link.peer || 'friend');
      if(S.role === 'guest'){ $('#room-title').textContent = 'Connected'; $('#room-text').textContent = 'Waiting for the host to kick off.' }
      sysMsg(`${link.peer || 'Friend'} joined (${link.signal}).`);
    }
    if(status === 'left' || status === 'lost'){
      sysMsg(text);
      if(S.role === 'host' && S.match){ K.leave(S.match, 'p1'); S.remote = {} }   // the computer takes over their team
    }
  }
  $('#start-online').onclick = () => {
    const seed = (Math.random() * 2 ** 32) >>> 0;
    S.names = [myName(), S.link.peer || 'Friend']; setNames();
    S.link.send('chat', {k: 'start', mode: S.mode, minutes: S.minutes, seed, names: S.names});
    startLocal(seed);
  };
  $('#leave-room').onclick = () => { if(S.link) S.link.close(); S.link = null; $('#room').hidden = true; $('#lobby').hidden = false; history.replaceState(null, '', location.pathname) };
  function onGame(msg){
    if(msg.k === 'in' && S.role === 'host') S.remote = msg.i;
    else if(msg.k === 'st' && S.role === 'guest'){
      S.snaps.push({at: performance.now(), s: msg.s}); if(S.snaps.length > 8) S.snaps.shift();
      for(const e of msg.s.ev || []) effect(e);
      S.lastScore = msg.s.sc;
      if(msg.s.ph === 'end' && !S.ended) finish();
    }
  }

  /* ---------------- Chat ---------------- */
  const QUICK = ['What a goal! ⚽', 'Unlucky 😅', 'Is that all? 😏', 'Nice save 🧤', 'Ref! 😤', 'GG 🤝'];
  $('#quick').innerHTML = QUICK.map(q => `<button type="button">${esc(q)}</button>`).join('');
  $('#quick').onclick = e => { const b = e.target.closest('button'); if(b) sendChat(b.textContent) };
  $('#send').onsubmit = e => { e.preventDefault(); sendChat($('#chat-in').value); $('#chat-in').value = '' };
  const BLOCK = /\b(f+u+c+k+\w*|sh[i1]t\w*|c+u+n+t+\w*|b[i1]tch\w*|n[i1]gg\w*|f[a4]g+\w*|wh[o0]re\w*|slut\w*|retard\w*)\b/gi;
  const clean = t => t.replace(BLOCK, w => w[0] + '*'.repeat(w.length - 1));
  function sendChat(text){
    text = clean(String(text).trim().slice(0, 140)); if(!text || !S.link) return;
    if(performance.now() - S.chatT < 1200){ sysMsg('Slow down a little.'); return }
    S.chatT = performance.now(); S.link.send('chat', {k: 'msg', name: myName(), text}); addMsg(myName(), text, true);
  }
  function onChat(msg){
    if(msg.k === 'msg') addMsg(String(msg.name || 'Friend').slice(0, 16), clean(String(msg.text || '').slice(0, 140)), false);
    else if(msg.k === 'start' && S.role === 'guest') startGuest(msg);
    else if(msg.k === 'end' && S.role === 'guest'){ S.lastScore = msg.score; if(!S.ended) finish() }
    else if(msg.k === 'rematch' && S.role === 'host') sysMsg(`${S.link.peer || 'Your friend'} wants a rematch. Press Rematch.`);
  }
  function addMsg(name, text, me){ const box = $('#msgs'); box.insertAdjacentHTML('beforeend', `<div class="msg${me ? ' me' : ''}"><small>${esc(name)}</small>${esc(text)}</div>`); box.scrollTop = box.scrollHeight }
  function sysMsg(text){ const box = $('#msgs'); box.insertAdjacentHTML('beforeend', `<div class="msg sys">${esc(text)}</div>`); box.scrollTop = box.scrollHeight }

  $('#again').onclick = () => {
    if(S.role === 'guest'){ S.link && S.link.send('chat', {k: 'rematch'}); $('#again').textContent = 'Asked!'; return }
    if(S.role === 'host'){ $('#start-online').onclick() } else $('#vs-cpu').onclick();
  };
  $('#menu-btn').onclick = () => { S.running = false; S.match = null; $('#final').hidden = true; if(S.link){ $('#room').hidden = false } else $('#lobby').hidden = false };

  // Supabase signalling only loads when configured.
  const cfg = window.LEAGUE_CONFIG || {};
  if(cfg.supabaseUrl && cfg.supabaseAnonKey && !window.supabase){
    const s = document.createElement('script'); s.src = 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/dist/umd/supabase.min.js'; document.head.appendChild(s);
  }
  // Links: ?room=CODE fills the code (add &auto=1 to join straight away, as challenges do);
  // ?host=CODE opens a room with that code, so a challenger and their friend meet in it.
  const params = new URLSearchParams(location.search), roomParam = params.get('room'), hostParam = params.get('host');
  const modeParam = params.get('mode'); if(K.MODES[modeParam]){ S.mode = modeParam; seg('mode', 'mode', S.mode) }
  if(hostParam && /^[A-Z0-9]{6}$/i.test(hostParam)) openRoom('host', hostParam.toUpperCase());
  else if(roomParam && /^[A-Z0-9]{6}$/i.test(roomParam)){ $('#code-in').value = roomParam.toUpperCase(); if(params.get('auto') === '1') openRoom('guest', roomParam.toUpperCase()) }
  window.__kick = S;
  requestAnimationFrame(frame);
})();
