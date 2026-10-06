// node --test community/web/match/engine.test.js
const test = require('node:test');
const assert = require('node:assert');
const K = require('./engine.js');

const play = (m, inputs = () => ({}), frames = Infinity) => { let n = 0; while(m.phase !== 'end' && n++ < frames) K.step(m, inputs(m)); return m };
const toPlay = m => { while(m.phase !== 'play') K.step(m, {}); return m };
const until = (m, done, max = 60) => { for(let i = 0; i < max && !done(m); i++) K.step(m, {}); return m };

test('every mode sets up full teams with one keeper each and a kickoff', () => {
  for(const [mode, cfg] of Object.entries(K.MODES)){
    const m = K.newMatch({mode});
    assert.strictEqual(m.players.length, cfg.slots.length * 2);
    assert.strictEqual(m.players.filter(p => p.gk).length, 2);
    assert.strictEqual(m.phase, 'kickoff');
    assert.ok(m.players.every(p => (p.team === 0 ? p.x <= 0 : p.x >= 0)), mode + ': each team in its own half');
  }
});

test('simulation is deterministic for a seed', () => {
  const a = play(K.newMatch({mode: '5v5', seed: 9, minutes: 1})), b = play(K.newMatch({mode: '5v5', seed: 9, minutes: 1}));
  assert.deepStrictEqual(a.score, b.score);
  assert.deepStrictEqual(K.snapshot(a).p, K.snapshot(b).p);
});

test('a free ball rolling over the line between the posts is a goal; outside the posts it rebounds', () => {
  const m = toPlay(K.newMatch({mode: '3v3'}));
  for(const p of m.players) p.y = 13;   // everyone out of the way
  Object.assign(m.ball, {owner: null, x: m.w / 2 - 0.3, y: 0, vx: 10, vy: 0, lastKicker: 1});
  until(m, m => m.phase === 'goal');
  assert.deepStrictEqual(m.score, [1, 0]);
  assert.strictEqual(m.phase, 'goal');
  const n = toPlay(K.newMatch({mode: '3v3'}));
  for(const p of n.players) p.y = 13;
  Object.assign(n.ball, {owner: null, x: n.w / 2 - 0.1, y: n.goal, vx: 10, vy: 0});
  until(n, n => n.ball.vx < 0, 10);
  assert.deepStrictEqual(n.score, [0, 0]);
  assert.ok(n.ball.vx < 0, 'rebounds off the end wall');
});

test('a keeper holding the ball on his own line never scores an own goal', () => {
  const m = toPlay(K.newMatch({mode: '3v3'}));
  const gk = m.players.find(p => p.gk && p.team === 0);
  gk.x = -m.w / 2 + 0.1; gk.y = 0; gk.dir = Math.PI;   // facing his own net
  for(const p of m.players) if(p !== gk) p.y = 12;
  Object.assign(m.ball, {owner: null, x: gk.x, y: 0, vx: 0, vy: 0, lastKicker: null});
  for(let i = 0; i < 120; i++) K.step(m, {});
  assert.deepStrictEqual(m.score, [0, 0]);
});

test('kickoff after a goal goes to the side that conceded', () => {
  const m = toPlay(K.newMatch({mode: '3v3'}));
  for(const p of m.players) p.y = 13;
  Object.assign(m.ball, {owner: null, x: m.w / 2 - 0.3, y: 0, vx: 10, vy: 0, lastKicker: 1});
  until(m, m => m.phase === 'goal');
  assert.strictEqual(m.phase, 'goal');
  while(m.phase === 'goal') K.step(m, {});
  assert.strictEqual(m.phase, 'kickoff');
  assert.strictEqual(m.kickoffTeam, 1);
  assert.strictEqual(m.ball.x, 0);
});

test('a human can join, move, pass and shoot; actions are counters so repeats are not double-counted', () => {
  const m = toPlay(K.newMatch({mode: '5v5', seed: 3}));
  assert.ok(K.join(m, 'me', 0));
  const me = K.controlled(m, 'me');
  Object.assign(m.ball, {owner: me.id, x: me.x, y: me.y});
  me.dir = 0;
  let shots = 0;
  const input = {mx: 1, my: 0, pass: 0, shoot: 1, power: 0.7, aimY: 0, tackle: 0, switch: 0};
  K.step(m, {me: {...input, shoot: 0}});
  for(let i = 0; i < 5; i++){ K.step(m, {me: input}); shots += m.events.filter(e => e.type === 'shot').length }
  assert.strictEqual(shots, 1, 'one press, one shot, even if the same input arrives again');
});

test('the full time whistle ends the match on time', () => {
  const m = play(K.newMatch({mode: '3v3', minutes: 1}));
  assert.strictEqual(m.phase, 'end');
  assert.ok(Math.abs(m.t - 60) < 0.05);
});

test('snapshots are compact and finite', () => {
  const m = play(K.newMatch({mode: '11v11', minutes: 1}), undefined, 600);
  const s = K.snapshot(m), raw = JSON.stringify(s);
  assert.strictEqual(s.p.length, 22);
  assert.ok(raw.length < 2500, 'snapshot ' + raw.length + ' bytes');
  assert.ok(s.p.every(p => p.slice(0, 3).every(Number.isFinite)));
});

test('computer-vs-computer scoring stays in an arcade band (regression guard)', () => {
  for(const [mode, lo, hi] of [['3v3', 3, 16], ['5v5', 3, 16], ['11v11', 0.3, 7]]){
    let goals = 0;
    for(let g = 0; g < 8; g++) goals += play(K.newMatch({mode, seed: 500 + g, minutes: 3})).score.reduce((a, b) => a + b, 0);
    const avg = goals / 8;
    assert.ok(avg >= lo && avg <= hi, `${mode} averaged ${avg} goals`);
  }
});
