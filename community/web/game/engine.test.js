// node --test community/web/game/engine.test.js
const test = require('node:test');
const assert = require('node:assert');
const E = require('./engine.js');

const play = (seq) => seq.reduce((s, [who, scored]) => s.over ? s : E.record(s, who, scored), E.newShootout());

test('seeded RNG and daily seed are deterministic', () => {
  const a = E.rng(E.daySeed('2026-10-06')), b = E.rng(E.daySeed('2026-10-06')), c = E.rng(E.daySeed('2026-10-07'));
  const xs = [a(), a(), a()];
  assert.deepStrictEqual(xs, [b(), b(), b()]);
  assert.notStrictEqual(xs[0], c());
  xs.forEach(x => assert.ok(x >= 0 && x < 1));
});

test('early finish when one side cannot catch up', () => {
  // You score 3 of 3, CPU misses 3 of 3: CPU has 2 kicks left, can reach 2 < 3.
  const s = play([['you', 1], ['cpu', 0], ['you', 1], ['cpu', 0], ['you', 1], ['cpu', 0]]);
  assert.strictEqual(s.winner, 'you');
  assert.deepStrictEqual(E.score(s), [3, 0]);
});

test('no early finish while the trailing side can still draw level', () => {
  const s = play([['you', 1], ['cpu', 0], ['you', 1], ['cpu', 0]]);
  assert.strictEqual(s.over, false);
});

test('sudden death decides only after equal kicks', () => {
  let s = play(Array.from({length: 5}, () => [['you', 1], ['cpu', 1]]).flat());
  assert.strictEqual(s.over, false);
  s = E.record(s, 'you', true);
  assert.strictEqual(s.over, false);       // CPU still to answer
  s = E.record(s, 'cpu', false);
  assert.strictEqual(s.winner, 'you');
});

test('shot geometry: wide is a miss, near the frame is the post, centre is on target', () => {
  assert.strictEqual(E.onTarget({x: 4.0, y: 1}), 'miss');
  assert.strictEqual(E.onTarget({x: 3.6, y: 1}), 'post');
  assert.strictEqual(E.onTarget({x: 0, y: 2.5}), 'post');
  assert.strictEqual(E.onTarget({x: 1, y: 1}), 'in');
});

test('keeper reach: slower shots and central shots are easier to reach', () => {
  assert.ok(E.reach(0.5) > E.reach(0.35));
  assert.ok(E.reach(0.4, 0) > E.reach(0.4, 3.4));
  assert.strictEqual(E.resolve({x: 1, y: 1, power: 0.3}, {x: 1, y: 1}), 'saved');
  assert.strictEqual(E.resolve({x: 3, y: 0.4, power: 0.9}, {x: -3, y: 0.4}), 'goal');
});

test('balance stays in a realistic band', () => {
  const r = E.rng(7), n = 10000;
  let goals = 0, saves = 0;
  for(let i = 0; i < n; i++){
    const aim = {x: (r() < .5 ? -1 : 1) * (2 + r() * 1.3), y: .3 + r() * 1.6};
    const s = E.strike(aim, .55 + r() * .3, i % 5, r);
    goals += E.resolve(s, E.cpuDive(s, i % 5, r)) === 'goal';
    const k = E.cpuKick(i % 5, r);
    saves += E.resolve(k, E.zoneDive(Math.floor(r() * 6))) === 'saved';
  }
  assert.ok(goals / n > 0.65 && goals / n < 0.85, 'player conversion ' + goals / n);
  assert.ok(saves / n > 0.12 && saves / n < 0.3, 'random-dive save rate ' + saves / n);
});

test('share text', () => {
  const s = play([['you', 1], ['cpu', 0], ['you', 1], ['cpu', 0], ['you', 1], ['cpu', 0]]);
  assert.strictEqual(E.shareText(s, '6 Oct'), 'Spot Kick 6 Oct: Won 3-0\nMe  ⚽⚽⚽\nCPU ❌❌❌');
});
