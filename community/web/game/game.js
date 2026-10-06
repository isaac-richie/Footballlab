(function(){
  'use strict';
  const E = window.SpotKick;
  const $ = s => document.querySelector(s);
  const store = {get(k){ try{ return localStorage.getItem(k) }catch{ return null } }, set(k, v){ try{ localStorage.setItem(k, v) }catch{} }};
  const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const lerp = (a, b, t) => a + (b - a) * t;
  const ease = t => 1 - Math.pow(1 - clamp(t, 0, 1), 3);

  const canvas = $('#pitch'), ctx = canvas.getContext('2d');
  const W = 960;
  let H = 600, L = {};

  /* ---------------- Layout ---------------- */
  function layout(){
    const cssW = canvas.parentElement.clientWidth || W;
    H = cssW < 600 ? 1000 : 600;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = W * dpr; canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const wide = H < 700, s = W * (wide ? 0.56 : 0.8) / 7.32, gy = wide ? H * 0.56 : H * 0.52, spotY = wide ? H * 0.9 : H * 0.9;
    L = {s, gy, spotY, horizon: gy - 2.44 * s - (wide ? 52 : 70), dpr};
    buildCrowd();
  }
  // Depth d in metres from the goal line (0) to the penalty spot (11), height h in metres.
  function project(x, d, h){
    const p = d / 11, k = 1 + 1.6 * p;
    return {x: W / 2 + x * L.s * k, y: L.gy + (L.spotY - L.gy) * p - h * L.s * k, k};
  }
  const toGoal = (sx, sy) => ({x: (sx - W / 2) / L.s, y: (L.gy - sy) / L.s});

  /* ---------------- Sound ---------------- */
  let audio = null, soundOn = store.get('sk-sound') !== 'off';
  const soundBtn = $('#sound');
  const paintSound = () => { soundBtn.textContent = soundOn ? '🔊' : '🔇'; soundBtn.setAttribute('aria-pressed', String(soundOn)) };
  paintSound();
  soundBtn.onclick = () => { soundOn = !soundOn; store.set('sk-sound', soundOn ? 'on' : 'off'); paintSound() };
  function ac(){ if(!audio){ try{ audio = new (window.AudioContext || window.webkitAudioContext)() }catch{ audio = null } } if(audio && audio.state === 'suspended') audio.resume(); return audio }
  function noise(dur, filterType, freq, q, peak, attack, release){
    const a = ac(); if(!a || !soundOn) return;
    const len = Math.floor(a.sampleRate * dur), buf = a.createBuffer(1, len, a.sampleRate), data = buf.getChannelData(0);
    for(let i = 0; i < len; i++) data[i] = Math.random() * 2 - 1;
    const src = a.createBufferSource(), f = a.createBiquadFilter(), g = a.createGain();
    src.buffer = buf; f.type = filterType; f.frequency.value = freq; f.Q.value = q;
    const t = a.currentTime;
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(peak, t + attack); g.gain.exponentialRampToValueAtTime(0.0001, t + attack + release);
    src.connect(f).connect(g).connect(a.destination); src.start(t); src.stop(t + dur);
  }
  function tone(freq, dur, peak, type = 'sine', vibrato = 0){
    const a = ac(); if(!a || !soundOn) return;
    const o = a.createOscillator(), g = a.createGain(), t = a.currentTime;
    o.type = type; o.frequency.value = freq;
    if(vibrato){ const l = a.createOscillator(), lg = a.createGain(); l.frequency.value = 28; lg.gain.value = vibrato; l.connect(lg).connect(o.frequency); l.start(t); l.stop(t + dur) }
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(peak, t + 0.01); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g).connect(a.destination); o.start(t); o.stop(t + dur + 0.02);
  }
  const sfx = {
    kick(){ tone(95, 0.16, 0.5); noise(0.08, 'lowpass', 500, 0.7, 0.35, 0.005, 0.07) },
    cheer(){ noise(2.4, 'bandpass', 1100, 0.6, 0.22, 0.25, 2.1) },
    groan(){ noise(1.3, 'bandpass', 380, 0.8, 0.16, 0.15, 1.1) },
    post(){ tone(1850, 0.35, 0.18, 'triangle'); tone(2620, 0.25, 0.1, 'sine') },
    whistle(){ tone(2900, 0.22, 0.12, 'sine', 140); setTimeout(() => tone(2900, 0.5, 0.12, 'sine', 140), 280) },
    tick(){ tone(660, 0.04, 0.05, 'square') },
  };

  /* ---------------- Crowd ---------------- */
  let crowd = [];
  function buildCrowd(){
    const r = E.rng(1234); crowd = [];
    const rows = Math.floor(L.horizon / 9);
    for(let row = 0; row < rows; row++){
      const y = 8 + row * 9, n = 110 + row * 3;
      for(let i = 0; i < n; i++){
        const hue = [210, 0, 45, 140, 280, 25][Math.floor(r() * 6)];
        crowd.push({x: (i + r()) / n * W, y: y + r() * 3, r: 2.2 + row * 0.12, c: `hsl(${hue} ${30 + r() * 40}% ${28 + r() * 30}%)`, phase: r() * 6.28});
      }
    }
  }

  /* ---------------- Game state ---------------- */
  const S = {phase: 'menu', mode: null, shoot: null, rngYou: null, rngCpu: null, aim: {x: 0, y: 1.1}, charging: false, chargeT0: 0, zone: 1,
    anim: null, shake: 0, particles: [], ripple: null, cheerT: 0, label: ''};
  const today = new Date().toISOString().slice(0, 10);
  const dayLabel = new Date(today + 'T12:00:00Z').toLocaleDateString(undefined, {day: 'numeric', month: 'short'});

  function hud(){
    const [a, b] = E.score(S.shoot);
    $('#s-you').textContent = a; $('#s-cpu').textContent = b;
    const dots = (arr, total) => Array.from({length: Math.max(5, total)}, (_, i) => `<i class="${i < arr.length ? (arr[i] ? 'g' : 'm') : ''}"></i>`).join('');
    const n = Math.max(S.shoot.you.length, S.shoot.cpu.length);
    $('#d-you').innerHTML = dots(S.shoot.you, n); $('#d-cpu').innerHTML = dots(S.shoot.cpu, n);
    const round = Math.max(S.shoot.you.length, S.shoot.cpu.length) + (S.phase === 'aim' ? 1 : 0);
    if(!S.mode){ $('#round').textContent = 'Penalty shootout'; return }
    $('#round').textContent = (S.mode === 'daily' ? `Daily Shootout · ${dayLabel}` : 'Quick match') + (round > 5 ? ' · Sudden death' : ` · Kick ${Math.min(5, Math.max(1, round))} of 5`);
  }
  const hint = t => { $('#hint').textContent = t };
  const say = t => { $('#live').textContent = t };
  function flash(text, color){
    const f = $('#flash'); f.textContent = text; f.style.color = color; f.classList.remove('on'); void f.offsetWidth; f.classList.add('on');
  }

  function start(mode){
    ac();
    S.mode = mode; S.shoot = E.newShootout();
    const seed = mode === 'daily' ? E.daySeed(today) : (Math.random() * 2 ** 32) >>> 0;
    S.rngCpu = E.rng(seed); S.rngYou = E.rng(seed ^ 0x9e3779b9);
    $('#menu').hidden = true; $('#end').hidden = true;
    sfx.whistle();
    nextTurn();
  }
  function nextTurn(){
    if(S.shoot.over) return finish();
    const youTaken = S.shoot.you.length, cpuTaken = S.shoot.cpu.length;
    if(youTaken <= cpuTaken) beginAim(); else beginKeep();
    hud();
  }
  function pressure(){ return Math.min(4, S.shoot.you.length) }

  function beginAim(){
    S.phase = 'aim'; S.aim = {x: 0, y: 1.1}; S.charging = false; S.anim = null;
    hint('Your penalty. Tap or move to aim, then press and hold to power up. Release to shoot.');
    say('Your penalty. Aim and shoot.');
  }
  function beginKeep(){
    S.phase = 'keep'; S.zone = 1;
    const kick = S.shoot.cpu.length;
    const shot = E.cpuKick(Math.min(4, kick), S.rngCpu);
    S.anim = {who: 'cpu', shot, t0: performance.now(), runup: 1500, flight: E.flight(shot.power).time * 1650, lean: shot.lean, done: false};
    hint('You are in goal. Watch the run-up, then tap where you will dive.');
    say('You are in goal. Choose where to dive.');
  }
  function shoot(power){
    const shot = E.strike(S.aim, power, pressure(), S.rngYou);
    const dive = E.cpuDive(shot, Math.min(4, S.shoot.you.length), S.rngCpu);
    S.phase = 'flight';
    S.anim = {who: 'you', shot, dive, outcome: E.resolve(shot, dive), t0: performance.now(), runup: 420, flight: E.flight(power).time * 1650, done: false};
    hint('');
  }
  function settle(){
    const a = S.anim; a.done = true;
    let outcome = a.outcome;
    if(a.who === 'cpu'){ a.dive = a.dive || E.zoneDive(S.zone); outcome = a.outcome = E.resolve(a.shot, a.dive) }  // dive was locked at the strike
    const scored = outcome === 'goal';
    S.shoot = E.record(S.shoot, a.who, scored);
    const mine = a.who === 'you';
    const text = {goal: mine ? 'GOAL!' : 'Goal', saved: mine ? 'Saved' : 'SAVED!', post: 'Off the post', miss: 'Over!'}[outcome];
    const good = mine ? scored : !scored;
    flash(text, good ? '#c2f25e' : '#ffffff');
    say(`${mine ? 'Your kick' : 'Their kick'}: ${text}`);
    if(outcome === 'post') sfx.post();
    if(good){ sfx.cheer(); S.cheerT = performance.now(); if(!reduced()) S.shake = 9 } else sfx.groan();
    if(outcome === 'goal') S.ripple = {x: a.shot.x, y: a.shot.y, t0: performance.now()};
    hud();
    setTimeout(nextTurn, 1500);
  }
  function finish(){
    S.phase = 'end'; hint('');
    const won = S.shoot.winner === 'you', [a, b] = E.score(S.shoot);
    if(won){ sfx.cheer(); burst() } else sfx.groan();
    if(S.mode === 'daily' && !store.get('sk-daily-' + today)) store.set('sk-daily-' + today, JSON.stringify({you: S.shoot.you, cpu: S.shoot.cpu, winner: S.shoot.winner}));
    const first = S.mode === 'daily' ? JSON.parse(store.get('sk-daily-' + today)) : S.shoot;
    const label = S.mode === 'daily' ? dayLabel : 'quick match';
    const text = E.shareText(first, label) + '\n' + location.href.split('#')[0];
    $('#end-title').textContent = won ? `You win ${a}-${b}!` : `Beaten ${a}-${b}`;
    $('#end-grid').textContent = first.you.map(x => x ? '⚽' : '❌').join('');
    $('#share-wa').href = 'https://wa.me/?text=' + encodeURIComponent(text);
    $('#share-copy').onclick = async () => { try{ await navigator.clipboard.writeText(text); $('#share-copy').textContent = 'Copied!' }catch{ prompt('Copy your result', text) } };
    $('#share-copy').textContent = 'Copy result';
    setTimeout(() => { $('#end').hidden = false }, 900);
    say(won ? `You won the shootout ${a} to ${b}` : `You lost the shootout ${a} to ${b}`);
    paintMenuNote();
  }
  function paintMenuNote(){
    const done = store.get('sk-daily-' + today);
    if(done){ const r = JSON.parse(done), [a, b] = E.score(r); $('#daily-note').textContent = `Today's result: ${r.winner === 'you' ? 'won' : 'lost'} ${a}-${b}. Replays don't change what you share. New shootout tomorrow.` }
    else $('#daily-note').textContent = 'Same keeper and takers for everyone today. Compare scores with friends.';
  }

  /* ---------------- Input ---------------- */
  function pointerGoal(e){ const r = canvas.getBoundingClientRect(); return toGoal((e.clientX - r.left) * W / r.width, (e.clientY - r.top) * H / r.height) }
  function setAim(g){ S.aim = {x: clamp(g.x, -4.4, 4.4), y: clamp(g.y, 0.1, 3.2)} }
  function pickZone(g){ const col = g.x < -1.22 ? 0 : g.x > 1.22 ? 2 : 1, row = g.y > 1.22 ? 1 : 0; if(S.zone !== col + row * 3){ S.zone = col + row * 3; sfx.tick() } }
  canvas.addEventListener('pointerdown', e => {
    ac();
    if(S.phase === 'aim'){ try{ canvas.setPointerCapture(e.pointerId) }catch{} setAim(pointerGoal(e)); S.charging = true; S.chargeT0 = performance.now() }
    else if(S.phase === 'keep' && !S.anim.kicked) pickZone(pointerGoal(e));
  });
  canvas.addEventListener('pointermove', e => { if(S.phase === 'aim') setAim(pointerGoal(e)); else if(S.phase === 'keep' && e.buttons && !S.anim.kicked) pickZone(pointerGoal(e)) });
  // A quick tap only aims; holding is what shoots, so phone users can place the aim first.
  const release = () => { if(S.phase !== 'aim' || !S.charging) return; S.charging = false; if(performance.now() - S.chargeT0 < 150) return; shoot(power()) };
  canvas.addEventListener('pointerup', release);
  canvas.addEventListener('pointercancel', () => { S.charging = false });
  document.addEventListener('keydown', e => {
    if(S.phase === 'aim'){
      const step = 0.18, k = e.key;
      if(k === 'ArrowLeft') setAim({x: S.aim.x - step, y: S.aim.y}); else if(k === 'ArrowRight') setAim({x: S.aim.x + step, y: S.aim.y});
      else if(k === 'ArrowUp') setAim({x: S.aim.x, y: S.aim.y + step}); else if(k === 'ArrowDown') setAim({x: S.aim.x, y: S.aim.y - step});
      else if(k === ' ' && !e.repeat && !S.charging){ S.charging = true; S.chargeT0 = performance.now() }
      else return;
      e.preventDefault();
    } else if(S.phase === 'keep' && !S.anim.kicked){
      let col = S.zone % 3, row = Math.floor(S.zone / 3);
      if(e.key === 'ArrowLeft') col = Math.max(0, col - 1); else if(e.key === 'ArrowRight') col = Math.min(2, col + 1);
      else if(e.key === 'ArrowUp') row = 1; else if(e.key === 'ArrowDown') row = 0; else return;
      e.preventDefault(); S.zone = col + row * 3; sfx.tick();
    } else if(S.phase === 'menu' && e.key === 'Enter'){ start('daily') }
  });
  document.addEventListener('keyup', e => { if(e.key === ' ') release() });
  const power = () => { const t = (performance.now() - S.chargeT0) / 1100; return (1 - Math.cos(t * Math.PI * 2)) / 2 };
  $('#play-daily').onclick = () => start('daily');
  $('#play-quick').onclick = () => start('quick');
  $('#again').onclick = () => { $('#end').hidden = true; $('#menu').hidden = false; S.phase = 'menu'; paintMenuNote() };

  /* ---------------- Drawing ---------------- */
  function drawStadium(now){
    const g = ctx.createLinearGradient(0, 0, 0, L.horizon);
    g.addColorStop(0, '#05070c'); g.addColorStop(1, '#141a26');
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, L.horizon);
    const excited = now - S.cheerT < 2200 ? 1 - (now - S.cheerT) / 2200 : 0;
    for(const p of crowd){
      const jump = excited * Math.max(0, Math.sin(now / 90 + p.phase)) * 5;
      ctx.fillStyle = p.c; ctx.beginPath(); ctx.arc(p.x, p.y - jump, p.r, 0, 6.283); ctx.fill();
    }
    if(Math.random() < 0.04 + excited * 0.3){ const x = Math.random() * W, y = Math.random() * L.horizon; ctx.fillStyle = '#ffffffcc'; ctx.beginPath(); ctx.arc(x, y, 2.5, 0, 6.283); ctx.fill() }
    // Floodlight glow and advertising boards
    for(const x of [W * 0.12, W * 0.88]){ const r = ctx.createRadialGradient(x, 0, 0, x, 0, 260); r.addColorStop(0, '#fff7d655'); r.addColorStop(1, '#fff7d600'); ctx.fillStyle = r; ctx.fillRect(x - 260, 0, 520, 260) }
    ctx.fillStyle = '#0d1b13'; ctx.fillRect(0, L.horizon - 16, W, 16);
    ctx.fillStyle = '#c2f25e'; ctx.font = '700 11px -apple-system,Inter,sans-serif'; ctx.textAlign = 'center';
    for(let x = 60; x < W; x += 240) ctx.fillText('SPOT KICK  ·  BEAT THE LAB', x + ((now / 40) % 240) - 120, L.horizon - 5);
  }
  function drawGrass(){
    const top = L.horizon, bottom = H, bands = 14;
    for(let i = 0; i < bands; i++){
      const t0 = i / bands, t1 = (i + 1) / bands, y0 = top + (bottom - top) * t0 ** 1.6, y1 = top + (bottom - top) * t1 ** 1.6;
      ctx.fillStyle = i % 2 ? '#2f7d43' : '#33894a'; ctx.fillRect(0, y0, W, y1 - y0 + 1);
    }
    const v = ctx.createRadialGradient(W / 2, H * 0.7, 50, W / 2, H * 0.7, W * 0.8);
    v.addColorStop(0, '#00000000'); v.addColorStop(1, '#00000059'); ctx.fillStyle = v; ctx.fillRect(0, top, W, bottom - top);
    ctx.strokeStyle = '#ffffffd9'; ctx.lineWidth = 3;
    const line = (pts) => { ctx.beginPath(); pts.forEach((p, i) => i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)); ctx.stroke() };
    line([project(-30, 0, 0), project(30, 0, 0)]);                                        // goal line
    line([project(-9.16, 0, 0), project(-9.16, 5.5, 0), project(9.16, 5.5, 0), project(9.16, 0, 0)]);  // six-yard box
    const sp = project(0, 11, 0); ctx.fillStyle = '#fff'; ctx.beginPath(); ctx.ellipse(sp.x, sp.y + 4, 7, 3, 0, 0, 6.283); ctx.fill();
  }
  function netPoint(x, y, depth, now){
    let dx = 0, dy = 0;
    if(S.ripple){ const age = (now - S.ripple.t0) / 1000; if(age < 1.2){ const d = Math.hypot(x - S.ripple.x, y - S.ripple.y), amp = Math.max(0, 0.45 - d * 0.18) * Math.exp(-age * 3) * Math.sin(age * 22 - d * 3); dy = 0; depth += amp } }
    return project(x, -depth, y + dy);
  }
  function drawGoal(now){
    const back = 1.6;
    ctx.strokeStyle = '#ffffff40'; ctx.lineWidth = 1;
    for(let x = -3.66; x <= 3.661; x += 0.3){ ctx.beginPath(); for(let y = 0; y <= 2.44; y += 0.2){ const d = back * (1 - y / 2.44 * 0.45), p = netPoint(x, y, d, now); y ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y) } ctx.stroke() }
    for(let y = 0; y <= 2.441; y += 0.3){ ctx.beginPath(); for(let x = -3.66; x <= 3.661; x += 0.2){ const d = back * (1 - y / 2.44 * 0.45), p = netPoint(x, y, d, now); x > -3.66 ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y) } ctx.stroke() }
    const a = project(-3.66, 0, 0), b = project(-3.66, 0, 2.44), c = project(3.66, 0, 2.44), d = project(3.66, 0, 0);
    ctx.strokeStyle = '#000a'; ctx.lineWidth = 12; ctx.beginPath(); ctx.moveTo(a.x + 3, a.y); ctx.lineTo(b.x + 3, b.y + 3); ctx.lineTo(c.x + 3, c.y + 3); ctx.lineTo(d.x + 3, d.y); ctx.stroke();
    ctx.strokeStyle = '#f8fafc'; ctx.lineWidth = 10; ctx.lineCap = 'round'; ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.lineTo(c.x, c.y); ctx.lineTo(d.x, d.y); ctx.stroke(); ctx.lineCap = 'butt';
  }
  function drawKeeper(now, kit){
    const a = S.anim; let cx = 0, cy = 1.0, ang = 0, stretch = 0;
    if(a && a.dive){
      const strikeT = a.t0 + a.runup + 60, k = ease((now - strikeT) / (a.flight * 0.95));
      if(now > strikeT){ cx = lerp(0, a.dive.x, k); cy = lerp(1.0, clamp(a.dive.y, 0.35, 2.2), k); ang = lerp(0, clamp(-a.dive.x * 0.42, -1.35, 1.35) * (a.dive.y > 1.6 ? 0.7 : 1), k); stretch = k }
    } else if(S.phase === 'keep' && a && !a.done){
      const z = E.ZONES[S.zone]; cx = z[0] * 0.08; ang = -z[0] * 0.03;   // shuffles toward your chosen side
    } else cx = Math.sin(now / 500) * 0.12;
    const base = project(cx, 0, cy), s = L.s;
    ctx.save(); ctx.translate(base.x, base.y); ctx.rotate(ang);
    const shadow = project(cx, 0, 0); ctx.restore();
    ctx.fillStyle = '#0005'; ctx.beginPath(); ctx.ellipse(shadow.x, shadow.y + 3, 0.5 * s, 0.1 * s, 0, 0, 6.283); ctx.fill();
    ctx.save(); ctx.translate(base.x, base.y); ctx.rotate(ang);
    const arm = 0.55 + stretch * 0.45;
    ctx.strokeStyle = kit.body; ctx.lineWidth = 0.14 * s; ctx.lineCap = 'round';
    ctx.beginPath(); ctx.moveTo(-0.18 * s, -0.3 * s); ctx.lineTo(-arm * s, -(0.55 + stretch * 0.2) * s); ctx.moveTo(0.18 * s, -0.3 * s); ctx.lineTo(arm * s, -(0.55 + stretch * 0.2) * s); ctx.stroke();
    ctx.fillStyle = kit.glove; for(const sx of [-1, 1]){ ctx.beginPath(); ctx.arc(sx * arm * s, -(0.55 + stretch * 0.2) * s, 0.1 * s, 0, 6.283); ctx.fill() }
    ctx.strokeStyle = kit.shorts; ctx.lineWidth = 0.15 * s; ctx.beginPath(); ctx.moveTo(-0.12 * s, 0.35 * s); ctx.lineTo(-0.2 * s, 0.95 * s); ctx.moveTo(0.12 * s, 0.35 * s); ctx.lineTo(0.2 * s, 0.95 * s); ctx.stroke();
    ctx.fillStyle = kit.body; roundRect(-0.24 * s, -0.42 * s, 0.48 * s, 0.82 * s, 0.12 * s); ctx.fill();
    ctx.fillStyle = '#e9b98f'; ctx.beginPath(); ctx.arc(0, -0.6 * s, 0.14 * s, 0, 6.283); ctx.fill();
    ctx.restore(); ctx.lineCap = 'butt';
  }
  function roundRect(x, y, w, h, r){ ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath() }
  function drawTaker(now, kit){
    const a = S.anim; let t = 1, lean = 0;
    if(a && !a.done) t = clamp((now - a.t0) / a.runup, 0, 1); else if(S.phase === 'aim') t = 0;
    if(a && a.who === 'cpu') lean = a.lean * (0.18 + 0.12 * t);
    const d = lerp(13.6, 11.35, ease(t)), x = lerp(H < 700 ? -1.9 : -1.05, -0.45, ease(t)) + lean * 0.4;
    const p = project(x, d, 0), s = L.s * p.k * 0.46, stride = Math.sin(t * Math.PI * 6) * (t < 1 ? 1 : 0);
    ctx.save(); ctx.translate(p.x, p.y); ctx.globalAlpha = 0.96;
    ctx.fillStyle = '#0006'; ctx.beginPath(); ctx.ellipse(0, 0, 0.45 * s, 0.1 * s, 0, 0, 6.283); ctx.fill();
    ctx.rotate(lean);
    ctx.strokeStyle = kit.shorts; ctx.lineWidth = 0.17 * s; ctx.lineCap = 'round';
    ctx.beginPath(); ctx.moveTo(-0.1 * s, -0.95 * s); ctx.lineTo(-0.15 * s + stride * 0.18 * s, 0); ctx.moveTo(0.1 * s, -0.95 * s); ctx.lineTo(0.15 * s - stride * 0.18 * s, 0); ctx.stroke();
    ctx.fillStyle = kit.body; roundRect(-0.27 * s, -1.75 * s, 0.54 * s, 0.85 * s, 0.13 * s); ctx.fill();
    ctx.fillStyle = kit.number; ctx.font = `800 ${0.34 * s}px -apple-system,Inter,sans-serif`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(kit.no, 0, -1.35 * s);
    ctx.fillStyle = '#3b2a20'; ctx.beginPath(); ctx.arc(0, -1.95 * s, 0.17 * s, 0, 6.283); ctx.fill();
    ctx.restore(); ctx.lineCap = 'butt';
  }
  function ballState(now){
    const a = S.anim;
    if(!a || now < a.t0 + a.runup) return {x: 0, d: 11, h: 0, spin: 0};
    const e = (now - a.t0 - a.runup) / a.flight, sh = a.shot, out = a.done ? a.outcome : null;
    if(e <= 1){ const k = e; return {x: sh.x * k, d: 11 * (1 - k), h: sh.y * k + 0.35 * 4 * k * (1 - k) * (1 - sh.power * 0.6), spin: e * 9} }
    const f = Math.min(1, (e - 1) * 1.6);
    if(out === 'goal') return {x: sh.x, d: -1.1 * ease(f), h: lerp(sh.y, 0.12, f * f), spin: 9 + f * 2};
    if(out === 'saved') return {x: sh.x + Math.sign(sh.x || 1) * 2.2 * ease(f), d: 3.2 * ease(f), h: Math.max(0.12, sh.y + 0.6 * f - 2 * f * f), spin: 9 - f * 6};
    if(out === 'post') return {x: sh.x - Math.sign(sh.x || 1) * 0.8 * f, d: 4 * ease(f), h: Math.max(0.12, sh.y - sh.y * f), spin: 9 - f * 6};
    return {x: sh.x * (1 + 0.25 * f), d: -3 * f, h: sh.y + 0.8 * f, spin: 9 + f * 3, fade: f};
  }
  function drawBall(now){
    const b = ballState(now), p = project(b.x, b.d, b.h), g = project(b.x, b.d, 0), r = 0.11 * L.s * p.k * 1.25;
    ctx.globalAlpha = 1 - (b.fade || 0);
    ctx.fillStyle = '#0006'; ctx.beginPath(); ctx.ellipse(g.x, g.y + 2, r * 1.1, r * 0.35, 0, 0, 6.283); ctx.fill();
    const grad = ctx.createRadialGradient(p.x - r * 0.35, p.y - r * 0.4, r * 0.2, p.x, p.y, r);
    grad.addColorStop(0, '#ffffff'); grad.addColorStop(1, '#c9d2dc');
    ctx.fillStyle = grad; ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, 6.283); ctx.fill();
    ctx.fillStyle = '#1c2430';
    ctx.beginPath(); ctx.arc(p.x + Math.cos(b.spin) * r * 0.15, p.y + Math.sin(b.spin) * r * 0.15, r * 0.24, 0, 6.283); ctx.fill();
    for(let i = 0; i < 5; i++){ const ang = b.spin + i * 1.2566; ctx.beginPath(); ctx.arc(p.x + Math.cos(ang) * r * 0.72, p.y + Math.sin(ang) * r * 0.72, r * 0.13, 0, 6.283); ctx.fill() }
    ctx.globalAlpha = 1;
  }
  function drawAim(now){
    const p = project(S.aim.x, 0, S.aim.y), wob = (0.1 + 0.035 * pressure()) * L.s;
    ctx.strokeStyle = '#c2f25e'; ctx.lineWidth = 2.5; ctx.setLineDash([6, 5]); ctx.beginPath(); ctx.arc(p.x, p.y, wob * 1.8, 0, 6.283); ctx.stroke(); ctx.setLineDash([]);
    ctx.beginPath(); ctx.moveTo(p.x - 10, p.y); ctx.lineTo(p.x + 10, p.y); ctx.moveTo(p.x, p.y - 10); ctx.lineTo(p.x, p.y + 10); ctx.stroke();
    // Power meter
    const x = W - 46, top = H * 0.3, h = H * 0.5, pw = S.charging ? power() : 0;
    ctx.fillStyle = '#0b0f14b3'; roundRect(x - 4, top - 4, 30, h + 8, 10); ctx.fill();
    ctx.fillStyle = '#7fe0a033'; ctx.fillRect(x, top + h * 0.15, 22, h * 0.3);
    ctx.fillStyle = '#f0727233'; ctx.fillRect(x, top, 22, h * 0.15);
    ctx.fillStyle = pw > 0.85 ? '#f07272' : pw > 0.55 ? '#7fe0a0' : '#f2b45e'; ctx.fillRect(x, top + h * (1 - pw), 22, h * pw);
    ctx.fillStyle = '#fff'; ctx.font = '700 11px -apple-system,Inter,sans-serif'; ctx.textAlign = 'center'; ctx.fillText('POWER', x + 11, top + h + 20);
  }
  function drawZones(){
    const a = S.anim; if(!a || a.done) return;
    for(let z = 0; z < 6; z++){
      const col = z % 3, row = Math.floor(z / 3), x0 = -3.66 + col * 2.44, y0 = row * 1.22;
      const p0 = project(x0, 0, y0), p1 = project(x0 + 2.44, 0, y0 + 1.22);
      ctx.fillStyle = z === S.zone ? '#c2f25e55' : '#ffffff17'; ctx.fillRect(p0.x + 2, p1.y + 2, p1.x - p0.x - 4, p0.y - p1.y - 4);
      ctx.strokeStyle = z === S.zone ? '#c2f25e' : '#ffffff55'; ctx.lineWidth = z === S.zone ? 3 : 1; ctx.strokeRect(p0.x + 2, p1.y + 2, p1.x - p0.x - 4, p0.y - p1.y - 4);
    }
  }
  function burst(){
    if(reduced()) return;
    const colors = ['#c2f25e', '#74bdfc', '#ffffff', '#f2b45e', '#f07272'];
    for(let i = 0; i < 160; i++) S.particles.push({x: W / 2 + (Math.random() - 0.5) * 300, y: H * 0.35, vx: (Math.random() - 0.5) * 9, vy: -Math.random() * 10 - 3, c: colors[i % 5], r: 3 + Math.random() * 4, life: 1});
  }
  function drawParticles(){
    S.particles = S.particles.filter(p => p.life > 0);
    for(const p of S.particles){ p.x += p.vx; p.y += p.vy; p.vy += 0.3; p.life -= 0.012; ctx.globalAlpha = Math.max(0, p.life); ctx.fillStyle = p.c; ctx.fillRect(p.x, p.y, p.r, p.r * 0.6) }
    ctx.globalAlpha = 1;
  }

  const KITS = {you: {body: '#c2f25e', shorts: '#1b2a12', number: '#13200a', no: '10'}, cpu: {body: '#74bdfc', shorts: '#0f2236', number: '#0b1b2b', no: '9'},
    youKeeper: {body: '#f2b45e', shorts: '#2a1a08', glove: '#ffffff'}, cpuKeeper: {body: '#e05a8a', shorts: '#2a0b18', glove: '#ffffff'}};

  function frame(now){
    ctx.save();
    if(S.shake > 0.3){ ctx.translate((Math.random() - 0.5) * S.shake, (Math.random() - 0.5) * S.shake); S.shake *= 0.86 }
    drawStadium(now); drawGrass(); drawGoal(now);
    const a = S.anim, cpuKeeps = S.phase === 'aim' || (a && a.who === 'you');
    if(S.phase === 'keep') drawZones();
    drawKeeper(now, cpuKeeps ? KITS.cpuKeeper : KITS.youKeeper);
    if(S.phase !== 'menu' && S.phase !== 'end') drawTaker(now, cpuKeeps ? KITS.you : KITS.cpu);
    drawBall(now);
    if(S.phase === 'aim') drawAim(now);
    drawParticles();
    ctx.restore();
    if(a && !a.done){
      if(now >= a.t0 + a.runup && !a.kicked){ a.kicked = true; sfx.kick(); if(a.who === 'cpu'){ a.dive = E.zoneDive(S.zone) } }
      if(now >= a.t0 + a.runup + a.flight) settle();
    }
    requestAnimationFrame(frame);
  }

  window.addEventListener('resize', layout);
  layout(); paintMenuNote(); S.shoot = E.newShootout(); hud();
  requestAnimationFrame(frame);
  window.__spotkick = S;  // handy for debugging in the console
})();
