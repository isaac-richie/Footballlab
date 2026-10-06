// Kickabout engine: top-down arcade football. Pure simulation, no drawing or networking.
// Units: metres and seconds. Home (team 0) attacks +x, away (team 1) attacks -x. Fixed 60 Hz steps.
(function(root){
  'use strict';
  const DT = 1 / 60;
  const MODES = {
    '3v3':   {w: 46,  h: 28, goal: 3.0,  slots: [[0.04, 0], [0.32, -0.18], [0.56, 0.18]]},
    '5v5':   {w: 58,  h: 36, goal: 4.0,  slots: [[0.04, 0], [0.26, -0.22], [0.26, 0.22], [0.55, -0.18], [0.6, 0.18]]},
    '11v11': {w: 100, h: 64, goal: 7.32, slots: [[0.03, 0], [0.19, -0.34], [0.17, -0.12], [0.17, 0.12], [0.19, 0.34],
                                                  [0.4, -0.34], [0.37, -0.12], [0.37, 0.12], [0.4, 0.34], [0.6, -0.12], [0.6, 0.12]]},
  };
  const P = {speed: 7.2, accel: 34, dribbleSpeed: 5.4, control: 0.75, gkControl: 1.15, ballFriction: 0.85,
    tackleRange: 1.35, tackleCd: 0.8, kickCd: 0.3, wall: 0.72, radius: 0.45};

  function rng(seed){ let a = seed >>> 0; return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ t >>> 15, t | 1); t ^= t + Math.imul(t ^ t >>> 7, t | 61); return ((t ^ t >>> 14) >>> 0) / 4294967296 } }
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const len = (x, y) => Math.hypot(x, y);

  function slotPos(m, team, slot, shift = 0, ballY = 0){
    const [fx, fy] = MODES[m.mode].slots[slot], L = m.w;
    const along = clamp(fx + shift, 0.02, 0.92) * L;
    const x = team === 0 ? -L / 2 + along : L / 2 - along;
    return {x, y: fy * m.h + (slot ? ballY * 0.35 : ballY * 0.15)};
  }

  function newMatch(opts = {}){
    const mode = MODES[opts.mode] ? opts.mode : '5v5', cfg = MODES[mode];
    const m = {mode, w: cfg.w, h: cfg.h, goal: cfg.goal, duration: (opts.minutes || 3) * 60, t: 0, score: [0, 0],
      phase: 'kickoff', phaseT: 0, kickoffTeam: 0, seed: opts.seed >>> 0 || 1, players: [], ball: null, events: [], controllers: {}, lastActions: {}};
    m.rand = rng(m.seed);
    for(let team = 0; team < 2; team++) cfg.slots.forEach((_, slot) => m.players.push({id: m.players.length, team, slot, gk: slot === 0,
      x: 0, y: 0, vx: 0, vy: 0, dir: team === 0 ? 0 : Math.PI, kickCd: 0, tackleCd: 0, stun: 0, ctrl: null}));
    m.ball = {x: 0, y: 0, vx: 0, vy: 0, owner: null, lastKicker: null, kickT: 0, shot: null, beaten: []};
    resetKickoff(m, 0);
    return m;
  }

  function resetKickoff(m, team){
    m.kickoffTeam = team; m.phase = 'kickoff'; m.phaseT = 0;
    for(const p of m.players){
      const s = slotPos(m, p.team, p.slot, -0.08);
      p.x = p.team === 0 ? Math.min(s.x, -1.5) : Math.max(s.x, 1.5); p.y = s.y; p.vx = p.vy = 0; p.stun = 0; p.kickCd = 0;
      p.dir = p.team === 0 ? 0 : Math.PI;
    }
    Object.assign(m.ball, {x: 0, y: 0, vx: 0, vy: 0, owner: null, shot: null});
    // The kicking-off side's most advanced player stands on the ball.
    const taker = m.players.filter(p => p.team === team && !p.gk).sort((a, b) => team === 0 ? b.x - a.x : a.x - b.x)[0];
    taker.x = team === 0 ? -0.6 : 0.6; taker.y = 0;
  }

  // ---------- Controllers (humans) ----------
  function join(m, controllerId, team){
    const free = m.players.filter(p => p.team === team && !p.gk && p.ctrl === null);
    if(!free.length) return false;
    const pick = free.sort((a, b) => len(a.x - m.ball.x, a.y - m.ball.y) - len(b.x - m.ball.x, b.y - m.ball.y))[0];
    pick.ctrl = controllerId; m.controllers[controllerId] = {team};
    return true;
  }
  function leave(m, controllerId){ for(const p of m.players) if(p.ctrl === controllerId) p.ctrl = null; delete m.controllers[controllerId]; delete m.lastActions[controllerId] }
  function controlled(m, controllerId){ return m.players.find(p => p.ctrl === controllerId) }
  function moveControl(m, controllerId, to){
    if(!to || to.gk || (to.ctrl !== null && to.ctrl !== controllerId)) return;
    const from = controlled(m, controllerId); if(from) from.ctrl = null; to.ctrl = controllerId;
  }

  // ---------- Ball actions ----------
  const goalX = (m, team) => team === 0 ? m.w / 2 : -m.w / 2;   // the goal a team attacks
  function kick(m, p, vx, vy, kind){
    const b = m.ball; b.owner = null; b.vx = vx; b.vy = vy; b.lastKicker = p.id; b.kickT = m.t; b.shot = kind === 'shot' ? p.team : null; b.beaten = [];
    p.kickCd = P.kickCd; m.events.push({type: kind, team: p.team, id: p.id});
  }
  function bestPassTarget(m, p, ax, ay){
    const dirX = len(ax, ay) > 0.2 ? ax / len(ax, ay) : Math.cos(p.dir), dirY = len(ax, ay) > 0.2 ? ay / len(ax, ay) : Math.sin(p.dir);
    let best = null, bestScore = -1e9;
    for(const q of m.players){
      if(q.team !== p.team || q === p) continue;
      const dx = q.x - p.x, dy = q.y - p.y, d = len(dx, dy);
      if(d < 3 || d > Math.max(32, m.w * 0.45)) continue;
      const cos = (dx * dirX + dy * dirY) / d;
      if(cos < 0.35) continue;
      let blocked = 0;
      for(const o of m.players){ if(o.team === p.team) continue; const t = clamp(((o.x - p.x) * dx + (o.y - p.y) * dy) / (d * d), 0, 1); if(len(p.x + dx * t - o.x, p.y + dy * t - o.y) < 1.4) blocked++ }
      const forward = (p.team === 0 ? dx : -dx) / d;
      const score = cos * 2 - d * 0.03 + forward * 0.6 - blocked * 1.5 - (q.gk ? 1.5 : 0);
      if(score > bestScore){ bestScore = score; best = q }
    }
    return best;
  }
  function pass(m, p, ax, ay){
    const q = bestPassTarget(m, p, ax, ay);
    if(!q){ const dx = len(ax, ay) > 0.2 ? ax / len(ax, ay) : Math.cos(p.dir), dy = len(ax, ay) > 0.2 ? ay / len(ax, ay) : Math.sin(p.dir); return kick(m, p, dx * 13, dy * 13, 'pass') }
    const tx = q.x + q.vx * 0.35, ty = q.y + q.vy * 0.35, d = len(tx - p.x, ty - p.y);
    // Speed chosen so the ball arrives at a receivable pace given ball friction.
    const speed = clamp(P.ballFriction * d + 5, 8, 26);
    kick(m, p, (tx - p.x) / d * speed, (ty - p.y) / d * speed, 'pass');
    return q;
  }
  function shoot(m, p, power, aimY){
    const gx = goalX(m, p.team), half = m.goal / 2;
    const dist = len(gx - p.x, p.y);
    const err = (0.12 + Math.max(0, power - 0.8) * 1.1 + dist / m.w * 0.25) * (m.rand() - 0.5) * m.goal;
    const ty = clamp(aimY, -1, 1) * half * 0.8 + err;
    const speed = 15 + 15 * clamp(power, 0, 1), d = len(gx - p.x, ty - p.y);
    kick(m, p, (gx - p.x) / d * speed, (ty - p.y) / d * speed, 'shot');
  }
  function tackle(m, p){
    p.tackleCd = P.tackleCd;
    const owner = m.ball.owner !== null ? m.players[m.ball.owner] : null;
    if(!owner || owner.team === p.team || len(owner.x - p.x, owner.y - p.y) > P.tackleRange){ p.stun = 0.25; return false }
    const front = Math.cos(Math.atan2(p.y - owner.y, p.x - owner.x) - owner.dir) > 0.3;   // tackling from in front is easier
    // Keepers are strong in one-on-ones; outfield tackles are easier from the front.
    if(m.rand() < (p.gk ? 0.8 : front ? 0.68 : 0.48)){
      owner.stun = 0.55; m.ball.owner = null; m.ball.vx = Math.cos(p.dir) * 5 + owner.vx * 0.3; m.ball.vy = Math.sin(p.dir) * 5 + owner.vy * 0.3;
      m.ball.lastKicker = p.id; m.ball.kickT = m.t; m.events.push({type: 'tackle', team: p.team, id: p.id}); return true;
    }
    p.stun = p.gk ? 0.3 : 0.45; m.events.push({type: 'miss_tackle', team: p.team, id: p.id}); return false;
  }

  // ---------- AI ----------
  function aiPlayer(m, p, ctx){
    const b = m.ball, own = b.owner !== null ? m.players[b.owner] : null;
    if(p.gk) return aiKeeper(m, p);
    if(own === p){
      const gx = goalX(m, p.team), dGoal = len(gx - p.x, p.y);
      // Shooting range scales with the pitch; closer and more central chances are taken more readily.
      const range = clamp(m.w * 0.27, 9, 25), angleOk = Math.abs(p.y) < m.goal + dGoal * 0.45;
      if(dGoal < range && angleOk && m.rand() < (dGoal < range * 0.5 ? 0.05 : 0.012)) return {act: 'shoot', power: 0.55 + m.rand() * 0.35, aimY: (m.rand() - 0.5) * 1.6};
      const pressed = m.players.some(o => o.team !== p.team && len(o.x - p.x, o.y - p.y) < 2.6 && (o.x - p.x) * (p.team === 0 ? 1 : -1) > -0.5);
      if(pressed && m.rand() < 0.08) return {act: 'pass', ax: p.team === 0 ? 1 : -1, ay: (m.rand() - 0.5)};
      return {mx: (gx - p.x) / dGoal, my: -p.y / dGoal * 1.2, sprint: 0.85};
    }
    if(p === ctx.chaser[p.team] || p === ctx.second[p.team] && len(b.x - p.x, b.y - p.y) < 8){
      const lead = own ? 0.2 : 0.3, tx = b.x + b.vx * lead, ty = b.y + b.vy * lead;
      const d = len(tx - p.x, ty - p.y);
      if(own && own.team !== p.team && d < P.tackleRange * 0.9 && p.tackleCd <= 0 && m.rand() < 0.1) return {act: 'tackle', mx: (tx - p.x) / (d || 1), my: (ty - p.y) / (d || 1)};
      return {mx: (tx - p.x) / (d || 1), my: (ty - p.y) / (d || 1), sprint: 1};
    }
    const attacking = own && own.team === p.team;
    const ballAlong = (p.team === 0 ? b.x + m.w / 2 : m.w / 2 - b.x) / m.w;
    const s = slotPos(m, p.team, p.slot, (attacking ? 0.1 : -0.06) + (ballAlong - 0.5) * 0.5, b.y / m.h);
    const d = len(s.x - p.x, s.y - p.y);
    return d < 0.8 ? {mx: 0, my: 0} : {mx: (s.x - p.x) / d, my: (s.y - p.y) / d, sprint: d > 6 ? 0.9 : 0.6};
  }
  function aiKeeper(m, p){
    const b = m.ball, own = b.owner === p.id, gx = goalX(m, 1 - p.team), sign = p.team === 0 ? 1 : -1;
    if(own){
      p.dir = p.team === 0 ? 0 : Math.PI;
      if(m.t - p.holdSince > 0.8) return {act: 'pass', ax: sign, ay: (m.rand() - 0.5) * 1.5};
      return {mx: sign * 0.3, my: 0, sprint: 0.3};   // step off the line
    }
    // A shot is coming: race to where it will cross the line (the dive).
    if(b.owner === null && b.shot !== null && b.shot !== p.team && (gx - b.x) * b.vx > 0 && Math.abs(b.vx) > 1){
      const t = (gx + sign * 0.4 - b.x) / b.vx, yi = clamp(b.y + b.vy * t, -m.goal / 2 - 0.5, m.goal / 2 + 0.5), tx = gx + sign * 0.4;
      const d = len(tx - p.x, yi - p.y);
      return d < 0.1 ? {mx: 0, my: 0} : {mx: (tx - p.x) / d, my: (yi - p.y) / d, sprint: 1.15};
    }
    // Close down a dribbler who gets near goal, and try to win the ball.
    const carrier = b.owner !== null ? m.players[b.owner] : null;
    if(carrier && carrier.team !== p.team && len(carrier.x - gx, carrier.y) < Math.min(10, m.w * 0.18)){
      const d = len(carrier.x - p.x, carrier.y - p.y);
      if(d < P.tackleRange && p.tackleCd <= 0 && m.rand() < 0.2) return {act: 'tackle', mx: 0, my: 0};
      return {mx: (carrier.x - p.x) / (d || 1), my: (carrier.y - p.y) / (d || 1), sprint: 1};
    }
    const ballDist = len(b.x - gx, b.y), rushRange = Math.min(9, m.w * 0.16);
    if(b.owner === null && ballDist < rushRange && (b.x - gx) * sign > 0){ const d = len(b.x - p.x, b.y - p.y); return {mx: (b.x - p.x) / d, my: (b.y - p.y) / d, sprint: 1} }
    const off = Math.min(1.6, m.goal * 0.3), tx = gx + sign * off, ty = clamp(b.y * 0.45, -m.goal / 2 + 0.3, m.goal / 2 - 0.3);
    const d = len(tx - p.x, ty - p.y);
    return d < 0.2 ? {mx: 0, my: 0} : {mx: (tx - p.x) / d, my: (ty - p.y) / d, sprint: 0.8};
  }

  // ---------- Step ----------
  // inputs: {controllerId: {mx, my, sprint, pass: n, shoot: n, power, aimY, tackle: n, switch: n}}; action fields are
  // cumulative counters so actions survive dropped or duplicated network packets.
  function step(m, inputs = {}){
    m.events = [];
    if(m.phase === 'end') return m;
    m.phaseT += DT;
    if(m.phase === 'goal'){ if(m.phaseT > 2.2) resetKickoff(m, m.kickoffTeam); return m }
    if(m.phase === 'kickoff'){ if(m.phaseT < 1.2) return m; m.phase = 'play'; m.events.push({type: 'whistle'}) }
    m.t += DT;
    if(m.t >= m.duration){ m.phase = 'end'; m.events.push({type: 'fulltime'}); return m }

    const b = m.ball;
    const ctx = {chaser: [null, null], second: [null, null]};
    for(const team of [0, 1]){
      const order = m.players.filter(p => p.team === team && !p.gk && p.ctrl === null).sort((a, c) => len(a.x - b.x, a.y - b.y) - len(c.x - b.x, c.y - b.y));
      const humanNear = m.players.some(p => p.team === team && p.ctrl !== null && order[0] && len(p.x - b.x, p.y - b.y) < len(order[0].x - b.x, order[0].y - b.y));
      ctx.chaser[team] = humanNear ? null : order[0] || null; ctx.second[team] = order[humanNear ? 0 : 1] || null;
    }
    for(const p of m.players){
      p.kickCd = Math.max(0, p.kickCd - DT); p.tackleCd = Math.max(0, p.tackleCd - DT);
      let cmd;
      if(p.ctrl !== null){
        const inp = inputs[p.ctrl] || {}, last = m.lastActions[p.ctrl] || {pass: inp.pass || 0, shoot: inp.shoot || 0, tackle: inp.tackle || 0, switch: inp.switch || 0};
        cmd = {mx: inp.mx || 0, my: inp.my || 0, sprint: 1};
        if((inp.switch || 0) > last.switch && b.owner !== p.id){
          const next = m.players.filter(q => q.team === p.team && !q.gk && q.ctrl === null).sort((a, c) => len(a.x - b.x, a.y - b.y) - len(c.x - b.x, c.y - b.y))[0];
          if(next) moveControl(m, p.ctrl, next);
        }
        if((inp.pass || 0) > last.pass) cmd.act = 'pass';
        else if((inp.shoot || 0) > last.shoot){ cmd.act = 'shoot'; cmd.power = inp.power || 0.6; cmd.aimY = inp.aimY || 0 }
        else if((inp.tackle || 0) > last.tackle) cmd.act = 'tackle';
        cmd.ax = inp.mx || 0; cmd.ay = inp.my || 0;
        m.lastActions[p.ctrl] = {pass: inp.pass || 0, shoot: inp.shoot || 0, tackle: inp.tackle || 0, switch: inp.switch || 0};
      } else cmd = aiPlayer(m, p, ctx);
      if(p.stun > 0){ p.stun -= DT; cmd = {mx: 0, my: 0} }
      // Actions
      if(cmd.act === 'pass' && b.owner === p.id){
        const q = pass(m, p, cmd.ax ?? Math.cos(p.dir), cmd.ay ?? Math.sin(p.dir));
        if(q && p.ctrl !== null && q.ctrl === null && !q.gk) p.pendingSwitch = q.id;
      } else if(cmd.act === 'shoot' && b.owner === p.id) shoot(m, p, cmd.power, cmd.aimY);
      else if(cmd.act === 'tackle' && p.tackleCd <= 0 && b.owner !== p.id) tackle(m, p);
      // Movement
      const mag = len(cmd.mx || 0, cmd.my || 0), max = (b.owner === p.id ? P.dribbleSpeed : P.speed) * (cmd.sprint || 1);
      const tvx = mag > 0.05 ? (cmd.mx / Math.max(1, mag)) * max : 0, tvy = mag > 0.05 ? (cmd.my / Math.max(1, mag)) * max : 0;
      const dvx = tvx - p.vx, dvy = tvy - p.vy, dv = len(dvx, dvy), a = P.accel * DT;
      if(dv > a){ p.vx += dvx / dv * a; p.vy += dvy / dv * a } else { p.vx = tvx; p.vy = tvy }
      p.x += p.vx * DT; p.y += p.vy * DT;
      if(len(p.vx, p.vy) > 0.4) p.dir = Math.atan2(p.vy, p.vx);
      // Only the goal mouth lets a player step beyond the end line.
      const depth = Math.abs(p.y) < m.goal / 2 ? 1.2 : -0.2;
      p.x = clamp(p.x, -m.w / 2 - depth, m.w / 2 + depth); p.y = clamp(p.y, -m.h / 2 + 0.3, m.h / 2 - 0.3);
    }
    // Light separation so players don't stack.
    for(let i = 0; i < m.players.length; i++) for(let j = i + 1; j < m.players.length; j++){
      const a = m.players[i], c = m.players[j], dx = c.x - a.x, dy = c.y - a.y, d = len(dx, dy);
      if(d > 0 && d < P.radius * 2){ const push = (P.radius * 2 - d) / 2; a.x -= dx / d * push; a.y -= dy / d * push; c.x += dx / d * push; c.y += dy / d * push }
    }
    // Ball
    if(b.owner !== null){
      const o = m.players[b.owner];
      b.x = o.x + Math.cos(o.dir) * 0.55; b.y = o.y + Math.sin(o.dir) * 0.55; b.vx = o.vx; b.vy = o.vy;
      // Walking the ball over the opponent's line between the posts is a goal; a player can
      // never carry it into their own net (keepers holding it on the line stay in play).
      if(Math.abs(b.x) > m.w / 2){
        const attacked = b.x > 0 ? 0 : 1;
        if(Math.abs(b.y) < m.goal / 2 && attacked === o.team) return scoreGoal(m, attacked, o.id);
        b.x = Math.sign(b.x) * (m.w / 2 - 0.05);
      }
    } else {
      const f = Math.exp(-P.ballFriction * DT); b.vx *= f; b.vy *= f;
      b.x += b.vx * DT; b.y += b.vy * DT;
      if(Math.abs(b.y) > m.h / 2){ b.y = Math.sign(b.y) * m.h / 2; b.vy = -b.vy * P.wall }
      if(Math.abs(b.x) > m.w / 2){
        if(Math.abs(b.y) < m.goal / 2) return scoreGoal(m, b.x > 0 ? 0 : 1, b.lastKicker);
        b.x = Math.sign(b.x) * m.w / 2; b.vx = -b.vx * P.wall; m.events.push({type: 'wall'});
      }
      // Possession: nearest eligible player within reach (keepers reach further near their goal).
      let best = null, bd = 1e9;
      const speed = len(b.vx, b.vy);
      for(const p of m.players){
        if(p.stun > 0 || (p.id === b.lastKicker && m.t - b.kickT < P.kickCd)) continue;
        const reach = p.gk ? P.gkControl : P.control, d = len(p.x - b.x, p.y - b.y);
        if(d > reach) continue;
        // Fast shots are harder to stop: keepers save by chance, outfielders only block.
        if(b.shot !== null && p.team !== b.shot){
          // One chance per player per shot: faster shots beat keepers more often; outfielders only
          // sometimes block fast shots. A beaten player cannot touch that shot again.
          if(b.beaten.includes(p.id)) continue;
          const stop = p.gk ? clamp(1.3 - speed / 40, 0.6, 0.94) : speed > 14 ? 0.35 : 1;
          if(m.rand() > stop){ b.beaten.push(p.id); continue }
        }
        if(d < bd){ bd = d; best = p }
      }
      if(best){
        if(b.shot !== null && best.team !== b.shot && best.gk) m.events.push({type: 'save', team: best.team, id: best.id});
        b.owner = best.id; b.shot = null; best.holdSince = m.t;
        if(best.gk) best.dir = best.team === 0 ? 0 : Math.PI;   // keepers turn to face upfield
        // A pass from a human hands their control to the receiver.
        for(const p of m.players) if(p.pendingSwitch === best.id){ if(p.ctrl !== null) moveControl(m, p.ctrl, best); p.pendingSwitch = undefined }
        // A human's team gaining the ball hands control to the receiver if no one is driving them.
        const humans = Object.keys(m.controllers).filter(c => m.controllers[c].team === best.team);
        if(best.ctrl === null && !best.gk && humans.length === 1){ moveControl(m, humans[0], best) }
        m.events.push({type: 'control', team: best.team, id: best.id});
      }
    }
    return m;
  }

  function scoreGoal(m, scorer, by){
    const b = m.ball;
    m.score[scorer]++; m.phase = 'goal'; m.phaseT = 0; m.kickoffTeam = 1 - scorer;
    m.events.push({type: 'goal', team: scorer, id: by});
    b.owner = null; b.vx *= 0.2; b.vy *= 0.2; b.x = Math.sign(b.x) * (m.w / 2 + 0.6);
    return m;
  }

  // ---------- Network snapshots ----------
  const r2 = v => Math.round(v * 100) / 100;
  function snapshot(m){
    return {t: r2(m.t), ph: m.phase, pt: r2(m.phaseT), sc: m.score, ko: m.kickoffTeam,
      p: m.players.map(p => [r2(p.x), r2(p.y), r2(p.dir), p.ctrl, p.stun > 0 ? 1 : 0]), b: [r2(m.ball.x), r2(m.ball.y), m.ball.owner], ev: m.events};
  }

  const api = {DT, MODES, P, rng, newMatch, step, join, leave, controlled, snapshot};
  if(typeof module !== 'undefined' && module.exports) module.exports = api; else root.Kickabout = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
