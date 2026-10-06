// Spot Kick engine: pure game rules, no drawing. Runs in the browser and in Node tests.
// Units are metres on the goal plane: x from -3.66 (left post) to 3.66, y from 0 (ground) to 2.44 (bar).
(function(root){
  const GOAL_HALF = 3.66, BAR = 2.44, BALL_R = 0.11, SPOT = 11;
  const ZONES = [[-2.4, 0.5], [0, 0.5], [2.4, 0.5], [-2.4, 1.8], [0, 1.8], [2.4, 1.8]];  // 0-2 low L/C/R, 3-5 high

  // Small, fast, seedable PRNG (mulberry32) so the daily shootout is identical for everyone.
  function rng(seed){
    let a = seed >>> 0;
    return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ t >>> 15, t | 1); t ^= t + Math.imul(t ^ t >>> 7, t | 61); return ((t ^ t >>> 14) >>> 0) / 4294967296 };
  }
  const gauss = r => { let u = 0, v = 0; while(!u) u = r(); while(!v) v = r(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v) };
  function daySeed(dateString){ let h = 2166136261; for(const c of 'spotkick:' + dateString){ h ^= c.charCodeAt(0); h = Math.imul(h, 16777619) } return h >>> 0 }

  // Power 0..1 sets speed; overhit (> 0.85) lifts the ball, underhit is slow and easier to save.
  function flight(power){ const speed = 17 + 15 * power; return {speed, time: SPOT / speed} }

  // Where the ball really goes: aim plus pressure wobble plus overhit lift.
  function strike(aim, power, pressure, r){
    const wobble = 0.1 + 0.035 * pressure;
    const lift = power > 0.85 ? (power - 0.85) * 9 : 0;
    return {x: aim.x + gauss(r) * wobble, y: Math.max(0.05, aim.y + gauss(r) * wobble * 0.7 + lift), power};
  }

  function onTarget(shot){
    if(Math.abs(shot.x) > GOAL_HALF + BALL_R || shot.y > BAR + BALL_R) return 'miss';
    if(Math.abs(shot.x) > GOAL_HALF - BALL_R || shot.y > BAR - BALL_R) return 'post';
    return 'in';
  }

  // Keeper reach grows with the time the ball takes to arrive, and shrinks toward the
  // corners, where a full-stretch dive is needed.
  const reach = (time, x = 0, y = 1) => (0.1 + 2.1 * time) * (1 - 0.4 * Math.max(0, (Math.abs(x) - 2.2) / 1.4)) * (y > 1.9 ? 0.85 : 1);

  // Computer keeper: guesses the side; the guess gets sharper as the shootout goes on.
  function cpuDive(shot, kick, r){
    // Slow shots are easier to read than well-struck ones.
    const sharp = Math.min(0.6, 0.3 + 0.03 * kick + Math.max(0, flight(shot.power).time - 0.4) * 1.5);
    const side = Math.sign(shot.x) || (r() < 0.5 ? -1 : 1);
    if(r() < sharp) return {x: shot.x + gauss(r) * 0.7, y: Math.min(BAR, Math.max(0.3, shot.y + gauss(r) * 0.4))};
    if(r() < 0.25) return {x: 0, y: 1};                                  // stays big in the middle
    return {x: -side * (1.6 + r() * 1.6), y: 0.4 + r() * 1.4};           // dives the wrong way
  }

  function resolve(shot, dive){
    const where = onTarget(shot);
    if(where === 'miss') return 'miss';
    if(where === 'post') return 'post';
    const d = Math.hypot(shot.x - dive.x, shot.y - dive.y);
    return d <= reach(flight(shot.power).time, shot.x, shot.y) * (dive.stretch || 1) ? 'saved' : 'goal';
  }

  // Computer penalty taker: picks a spot, sometimes a corner, sometimes a chip down the middle.
  function cpuKick(kick, r){
    const corner = r() < 0.8, x = corner ? (r() < 0.5 ? -1 : 1) * (1.9 + r() * 1.3) : (r() - 0.5) * 1.6;
    const y = r() < 0.4 ? 1.5 + r() * 0.75 : 0.2 + r() * 0.8;
    const power = 0.45 + r() * 0.45;
    const shot = strike({x, y}, power, kick * 0.6, r);
    // The run-up leans toward the real side 60% of the time: a tell a sharp keeper can read.
    shot.lean = r() < 0.6 ? Math.sign(shot.x) || 0 : (r() < 0.5 ? -1 : 1);
    return shot;
  }

  // Player keeper: picks one of six zones; a dive covers that zone's centre.
  // A committed full-stretch dive covers more than the computer keeper's reactive one.
  const zoneDive = z => ({x: ZONES[z][0], y: ZONES[z][1], stretch: z % 3 === 1 ? 1 : 1.35});

  // Shootout bookkeeping: best of five each, then sudden death in pairs.
  function newShootout(){ return {you: [], cpu: [], over: false, winner: null} }
  function record(state, who, scored){
    const s = {...state, you: state.you.slice(), cpu: state.cpu.slice()};
    s[who].push(!!scored);
    const goals = k => s[k].filter(Boolean).length, taken = k => s[k].length;
    if(taken('you') <= 5 && taken('cpu') <= 5){
      const leftYou = 5 - taken('you'), leftCpu = 5 - taken('cpu');
      if(goals('you') > goals('cpu') + leftCpu) s.winner = 'you';
      else if(goals('cpu') > goals('you') + leftYou) s.winner = 'cpu';
    } else if(taken('you') === taken('cpu') && goals('you') !== goals('cpu')){
      s.winner = goals('you') > goals('cpu') ? 'you' : 'cpu';
    }
    s.over = !!s.winner;
    return s;
  }
  const score = s => [s.you.filter(Boolean).length, s.cpu.filter(Boolean).length];

  function shareText(s, label){
    const row = arr => arr.map(x => x ? '⚽' : '❌').join('');
    const [a, b] = score(s);
    return `Spot Kick ${label}: ${s.winner === 'you' ? 'Won' : 'Lost'} ${a}-${b}\nMe  ${row(s.you)}\nCPU ${row(s.cpu)}`;
  }

  const api = {GOAL_HALF, BAR, ZONES, rng, daySeed, flight, strike, onTarget, reach, cpuDive, resolve, cpuKick, zoneDive, newShootout, record, score, shareText};
  if(typeof module !== 'undefined' && module.exports) module.exports = api; else root.SpotKick = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
