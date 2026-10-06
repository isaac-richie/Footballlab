// Data layer: the same interface backed by Supabase, or by an in-memory demo.
(function(){
  const lockTime = f => new Date(f.kickoff_at || f.kickoff_date + 'T00:00:00Z');
  const isOpen = f => f.status === 'scheduled' && Date.now() < lockTime(f).getTime();
  const outcome = f => f.home_goals > f.away_goals ? 0 : f.home_goals === f.away_goals ? 1 : 2;
  const brier = (p, o) => p.reduce((s, x, i) => s + (x - (i === o ? 1 : 0)) ** 2, 0);
  function score(pred, f){
    const o = outcome(f), mine = [pred.p_home, pred.p_draw, pred.p_away].map(x => x / 100);
    const lab = [f.lab_home ?? 1 / 3, f.lab_draw ?? 1 / 3, f.lab_away ?? 1 / 3].map(Number);
    return {outcome: o, brier: brier(mine, o), lab_brier: brier(lab, o), points: Math.round((brier(lab, o) - brier(mine, o)) * 10000) / 100,
      p_outcome: [pred.p_home, pred.p_draw, pred.p_away][o], lab_outcome: lab[o],
      top_pick_right: Math.max(...mine) === mine[o]};
  }
  const weekStart = d => { const x = new Date(d + 'T12:00:00Z'); x.setUTCDate(x.getUTCDate() - ((x.getUTCDay() + 6) % 7)); return x.toISOString().slice(0, 10) };
  window.LeagueMath = {lockTime, isOpen, outcome, score, weekStart};

  /* ---------------- Supabase ---------------- */
  function supabaseBackend(cfg){
    const sb = window.supabase.createClient(cfg.supabaseUrl, cfg.supabaseAnonKey);
    let session = null;
    const must = r => { if(r.error) throw new Error(r.error.message); return r.data };
    const uid = () => session && session.user.id;
    return {
      demo: false,
      async init(onChange){
        session = must(await sb.auth.getSession()).session;
        sb.auth.onAuthStateChange((_e, s) => { session = s; onChange() });
      },
      user: () => session && {id: session.user.id, email: session.user.email},
      async sendCode(email){ must(await sb.auth.signInWithOtp({email, options: {shouldCreateUser: true}})) },
      async verifyCode(email, token){ session = must(await sb.auth.verifyOtp({email, token, type: 'email'})).session },
      async signOut(){ must(await sb.auth.signOut()); session = null },
      async profile(){ if(!uid()) return null; return must(await sb.from('profiles').select('username').eq('id', uid()).maybeSingle()) },
      async saveUsername(username){ must(await sb.from('profiles').upsert({id: uid(), username})) },
      async fixtures(from, to){ return must(await sb.from('fixtures').select('*').gte('kickoff_date', from).lte('kickoff_date', to).order('kickoff_date').order('home')) },
      async myPredictions(ids){
        if(!uid() || !ids.length) return {};
        const rows = must(await sb.from('predictions').select('*').eq('user_id', uid()).in('fixture_id', ids));
        return Object.fromEntries(rows.map(r => [r.fixture_id, r]));
      },
      async savePrediction(fixture_id, p_home, p_draw, p_away){
        must(await sb.from('predictions').upsert({user_id: uid(), fixture_id, p_home, p_draw, p_away}));
      },
      async entryCounts(ids){ if(!ids.length) return {}; return Object.fromEntries(must(await sb.rpc('entry_counts', {ids})).map(r => [r.fixture_id, r.players])) },
      async crowd(ids){ if(!ids.length) return {}; return Object.fromEntries(must(await sb.from('crowd').select('*').in('fixture_id', ids)).map(r => [r.fixture_id, r])) },
      async leaderboard(season){ return must(await sb.from('leaderboard').select('*').eq('season', season).order('points', {ascending: false}).limit(200)) },
      async weekly(round){ return must(await sb.from('weekly').select('*').eq('round', round).order('points', {ascending: false}).limit(200)) },
      async latestRound(){ const r = must(await sb.from('points').select('round').order('round', {ascending: false}).limit(1)); return r[0] && r[0].round },
      async myPoints(){
        if(!uid()) return [];
        const pts = must(await sb.from('points').select('*').eq('user_id', uid()).order('kickoff_date', {ascending: false}).limit(100));
        if(!pts.length) return [];
        const fx = Object.fromEntries(must(await sb.from('fixtures').select('*').in('id', pts.map(p => p.fixture_id))).map(f => [f.id, f]));
        return pts.map(p => ({...p, fixture: fx[p.fixture_id]}));
      },
      async myBadges(){ if(!uid()) return []; return must(await sb.from('badges').select('*').eq('user_id', uid())) },
      async myStreak(){
        if(!uid()) return 0;
        const rows = must(await sb.from('streaks').select('*').eq('user_id', uid()).order('last_round', {ascending: false}).limit(1));
        return rows[0] ? rows[0].weeks : 0;
      },
      async groups(){
        if(!uid()) return [];
        const gs = must(await sb.from('groups').select('id,name,invite_code,owner'));
        const members = must(await sb.from('group_members').select('group_id,user_id'));
        return gs.map(g => ({...g, members: members.filter(m => m.group_id === g.id).map(m => m.user_id)}));
      },
      async createGroup(name){ must(await sb.from('groups').insert({name, owner: uid()})) },
      async joinGroup(code){ must(await sb.rpc('join_group', {code})) },
      async leaveGroup(id){ must(await sb.from('group_members').delete().eq('group_id', id).eq('user_id', uid())) },
    };
  }

  /* ---------------- Demo ---------------- */
  function demoBackend(){
    const day = n => { const d = new Date(); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10) };
    const teams = [['Arsenal FC', 'Leeds United FC', .66, .21], ['Sunderland AFC', 'Brighton & Hove Albion FC', .33, .26], ['Chelsea FC', 'AFC Bournemouth', .48, .24],
      ['Liverpool FC', 'Everton FC', .58, .23], ['Aston Villa FC', 'Brentford FC', .43, .25], ['Real Madrid CF', 'Sevilla FC', .64, .21],
      ['FC Barcelona', 'Getafe CF', .72, .19], ['FC Bayern München', 'VfB Stuttgart', .69, .17], ['FC Internazionale Milano', 'AS Roma', .51, .26],
      ['Paris Saint-Germain FC', 'OGC Nice', .67, .19]];
    const league = i => i < 5 ? ['en.1', 'Premier League'] : i < 7 ? ['es.1', 'La Liga'] : i < 8 ? ['de.1', 'Bundesliga'] : i < 9 ? ['it.1', 'Serie A'] : ['fr.1', 'Ligue 1'];
    const fixtures = [];
    teams.forEach(([h, a, ph, pd], i) => {
      const [lid, lname] = league(i);
      fixtures.push({id: 'u' + i, league_id: lid, league_name: lname, season: '2026-27', kickoff_date: day(i < 5 ? 4 : 5), kickoff_at: null, home: h, away: a,
        status: 'scheduled', home_goals: null, away_goals: null, lab_home: ph, lab_draw: pd, lab_away: +(1 - ph - pd).toFixed(4)});
      const score = [[2, 0], [1, 2], [1, 1], [3, 1], [0, 0], [2, 1], [4, 0], [3, 3], [0, 1], [2, 2]][i];
      fixtures.push({id: 'f' + i, league_id: lid, league_name: lname, season: '2026-27', kickoff_date: day(i < 5 ? -3 : -2), kickoff_at: null, home: a, away: h,
        status: 'finished', home_goals: score[0], away_goals: score[1], lab_home: +(1 - ph - pd).toFixed(4) + .05, lab_draw: pd, lab_away: ph - .05});
    });
    const names = ['naija_oracle', 'xg_merchant', 'lagos_tactician', 'draw_doctor', 'upset_hunter', 'calm_closer', 'abuja_analyst', 'pressing_trap'];
    const players = names.map((n, i) => ({id: 'p' + i, username: n}));
    const preds = [];
    let seed = 7; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
    players.forEach(pl => fixtures.forEach(f => {
      if(rnd() < .25) return;
      let h = Math.max(5, Math.round((f.lab_home + (rnd() - .5) * .3) * 100)), d = Math.max(5, Math.round((f.lab_draw + (rnd() - .5) * .15) * 100));
      if(h + d > 95) h = 95 - d;
      preds.push({user_id: pl.id, fixture_id: f.id, p_home: h, p_draw: d, p_away: 100 - h - d});
    }));
    const me = {id: 'me', email: 'you@example.com'}; let signedIn = false, myName = null;
    const groups = [{id: 'g1', name: 'Sunday League Legends', invite_code: 'DEMO2026', owner: 'p0', members: ['p0', 'p1', 'p4']}];
    const byId = Object.fromEntries(fixtures.map(f => [f.id, f]));
    const scored = () => preds.filter(p => byId[p.fixture_id].status === 'finished').map(p => ({...p, ...score(p, byId[p.fixture_id]), fixture: byId[p.fixture_id], round: weekStart(byId[p.fixture_id].kickoff_date)}));
    const userName = id => id === 'me' ? myName : (players.find(p => p.id === id) || {}).username;
    const table = rows => {
      const agg = {};
      rows.forEach(r => { const a = agg[r.user_id] ||= {user_id: r.user_id, username: userName(r.user_id), predictions: 0, points: 0, brier: 0, hits: 0, beat_lab: 0};
        a.predictions++; a.points += r.points; a.brier += r.brier; a.hits += r.top_pick_right; a.beat_lab += r.points > 0 });
      return Object.values(agg).filter(a => a.username).map(a => ({...a, points: Math.round(a.points * 100) / 100, avg_brier: a.brier / a.predictions, hit_rate: a.hits / a.predictions})).sort((x, y) => y.points - x.points);
    };
    const wait = (v) => new Promise(r => setTimeout(() => r(v), 120));
    let notify = () => {};
    return {
      demo: true,
      async init(onChange){ notify = onChange },
      user: () => signedIn ? me : null,
      async sendCode(){ await wait() },
      async verifyCode(_e, code){ if(code !== '123456') throw new Error('In demo mode the code is 123456.'); signedIn = true;
        // Give the demo player some finished picks so Results has content.
        if(!preds.some(p => p.user_id === 'me')) ['f0', 'f1', 'f3', 'f6', 'f8'].forEach((id, i) => preds.push({user_id: 'me', fixture_id: id, p_home: [20, 30, 25, 15, 30][i], p_draw: [25, 25, 25, 15, 30][i], p_away: [55, 45, 50, 70, 40][i]}));
        notify() },
      async signOut(){ signedIn = false; notify() },
      async profile(){ return signedIn && myName ? {username: myName} : null },
      async saveUsername(n){ if(players.some(p => p.username === n)) throw new Error('That username is taken.'); myName = n; await wait() },
      async fixtures(from, to){ return wait(fixtures.filter(f => f.kickoff_date >= from && f.kickoff_date <= to).sort((a, b) => a.kickoff_date.localeCompare(b.kickoff_date))) },
      async myPredictions(ids){ return wait(Object.fromEntries(preds.filter(p => p.user_id === 'me' && ids.includes(p.fixture_id)).map(p => [p.fixture_id, p]))) },
      async savePrediction(fixture_id, p_home, p_draw, p_away){
        if(!isOpen(byId[fixture_id])) throw new Error('This match has locked.');
        const i = preds.findIndex(p => p.user_id === 'me' && p.fixture_id === fixture_id);
        const row = {user_id: 'me', fixture_id, p_home, p_draw, p_away};
        i >= 0 ? preds[i] = row : preds.push(row); await wait();
      },
      async entryCounts(ids){ const c = {}; preds.forEach(p => { if(ids.includes(p.fixture_id)) c[p.fixture_id] = (c[p.fixture_id] || 0) + 1 }); return wait(c) },
      async crowd(ids){
        const out = {};
        ids.filter(id => !isOpen(byId[id])).forEach(id => { const ps = preds.filter(p => p.fixture_id === id); if(!ps.length) return;
          const avg = k => Math.round(ps.reduce((s, p) => s + p[k], 0) / ps.length * 10) / 10;
          out[id] = {fixture_id: id, players: ps.length, p_home: avg('p_home'), p_draw: avg('p_draw'), p_away: avg('p_away')} });
        return wait(out);
      },
      async leaderboard(){ return wait(table(scored())) },
      async weekly(round){ return wait(table(scored().filter(r => r.round === round))) },
      async latestRound(){ return scored().map(r => r.round).sort().pop() },
      async myPoints(){ return wait(scored().filter(r => r.user_id === 'me').sort((a, b) => b.fixture.kickoff_date.localeCompare(a.fixture.kickoff_date))) },
      async myBadges(){ const s = scored().filter(r => r.user_id === 'me'), b = [];
        s.forEach(r => { if(r.p_outcome >= 50 && r.lab_outcome < .25) b.push({badge: 'upset_caller', fixture_id: r.fixture_id}); if(r.p_outcome >= 80) b.push({badge: 'bang_on', fixture_id: r.fixture_id}) });
        return wait(b) },
      async myStreak(){ return signedIn ? 1 : 0 },
      async groups(){ return wait(signedIn ? groups.filter(g => g.members.includes('me')) : []) },
      async createGroup(name){ groups.push({id: 'g' + (groups.length + 1), name, invite_code: Math.random().toString(16).slice(2, 10).toUpperCase(), owner: 'me', members: ['me']}); await wait() },
      async joinGroup(code){ const g = groups.find(x => x.invite_code === code.trim().toUpperCase()); if(!g) throw new Error('No league with that code. Try DEMO2026.'); if(!g.members.includes('me')) g.members.push('me'); await wait() },
      async leaveGroup(id){ const g = groups.find(x => x.id === id); g.members = g.members.filter(m => m !== 'me'); await wait() },
    };
  }

  const cfg = window.LEAGUE_CONFIG || {};
  window.LeagueData = cfg.supabaseUrl && cfg.supabaseAnonKey && window.supabase ? supabaseBackend(cfg) : demoBackend();
})();
