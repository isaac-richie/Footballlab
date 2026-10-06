(function(){
  const D = window.LeagueData, M = window.LeagueMath;
  const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const store = {get(k){ try{ return localStorage.getItem(k) }catch{ return null } }, set(k, v){ try{ localStorage.setItem(k, v) }catch{} }};
  const motionOK = () => !matchMedia('(prefers-reduced-motion: reduce)').matches;
  const pts = x => (x > 0 ? '+' : '') + Number(x).toFixed(1);
  const dayLabel = d => new Date(d + 'T12:00:00Z').toLocaleDateString(undefined, {weekday: 'long', day: 'numeric', month: 'short'});
  const isoDay = n => { const d = new Date(); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10) };
  const state = {view: 'play', league: store.get('btl-league') || 'all', scope: 'season', fixtures: [], preds: {}, profile: null, groups: [], group: null};

  function crest(name){
    const skip = new Set(['fc', 'cf', 'ac', 'afc', 'as', 'rc', 'sc', 'ogc', 'vfb', 'vfl', 'club', 'de', '1.']);
    const w = name.normalize('NFKD').replace(/[̀-ͯ]/g, '').split(/[\s-]+/).filter(x => /^[a-z0-9]/i.test(x) && !skip.has(x.toLowerCase()));
    const ini = (w.length > 1 ? w[0][0] + w[1][0] : (w[0] || name).slice(0, 2)).toUpperCase();
    let h = 0; for(const c of name) h = (h * 31 + c.charCodeAt(0)) % 360;
    return `<span class="crest" style="background:linear-gradient(140deg,hsl(${h} 62% 50%),hsl(${(h + 28) % 360} 58% 34%))" aria-hidden="true">${esc(ini)}</span>`;
  }
  function toast(msg){ const t = $('#toast'); t.textContent = msg; t.classList.add('on'); clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove('on'), 2200) }
  function countUp(el, to, dp = 1){
    if(!motionOK()){ el.textContent = pts(to); return }
    const t0 = performance.now();
    const tick = now => { const k = Math.min(1, (now - t0) / 800), v = to * (1 - (1 - k) ** 3); el.textContent = (to > 0 ? '+' : '') + v.toFixed(dp); if(k < 1) requestAnimationFrame(tick) };
    requestAnimationFrame(tick);
  }

  /* ---------- Theme + views ---------- */
  const applyTheme = t => t ? document.documentElement.dataset.theme = t : delete document.documentElement.dataset.theme;
  applyTheme(store.get('btl-theme'));
  $('#theme').onclick = () => { const next = getComputedStyle(document.documentElement).colorScheme.includes('dark') ? 'light' : 'dark'; applyTheme(next); store.set('btl-theme', next) };
  function showView(){
    const v = (location.hash || '#play').slice(1);
    state.view = ['play', 'table', 'results', 'leagues'].includes(v) ? v : 'play';
    const swap = () => {
      $$('[data-panel]').forEach(p => p.hidden = p.dataset.panel !== state.view);
      $$('.nav a').forEach(a => a.dataset.view === state.view ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current'));
    };
    if(document.startViewTransition && motionOK() && !document.hidden){ const t = document.startViewTransition(swap); t.ready.catch(() => {}); t.finished.catch(() => {}); t.updateCallbackDone.catch(() => {}) }
    else swap();
    ({play: renderPlay, table: renderBoard, results: renderResults, leagues: renderGroups})[state.view]();
  }
  window.addEventListener('hashchange', showView);

  /* ---------- Account ---------- */
  async function refreshAccount(){
    const u = D.user();
    state.profile = u ? await D.profile() : null;
    $('#account').textContent = u ? (state.profile ? '@' + state.profile.username : 'Set username') : 'Sign in';
    if(u && !state.profile) $('#name-dialog').showModal();
    $('#banner').innerHTML = D.demo ? `<div class="card"><span class="mark" style="width:22px;height:22px;font-size:10px">!</span><span><b>Demo mode.</b> Sample players and fixtures. Sign in with any email and the code <b>123456</b>. Connect Supabase in config.js to go live.</span></div>` : '';
  }
  $('#account').onclick = async () => {
    if(!D.user()){ $('#otp-field').hidden = true; $('#auth-submit').textContent = 'Send code'; $('#auth-error').textContent = ''; $('#auth-dialog').showModal(); return }
    if(!state.profile){ $('#name-dialog').showModal(); return }
    if(confirm('Sign out?')){ await D.signOut(); await refreshAccount(); showView() }
  };
  $('#auth-form').onsubmit = async e => {
    if(e.submitter && e.submitter.value === 'cancel') return;
    e.preventDefault();
    const email = $('#auth-email').value.trim(), code = $('#auth-code').value.trim();
    $('#auth-error').textContent = '';
    try{
      if($('#otp-field').hidden){ await D.sendCode(email); $('#otp-field').hidden = false; $('#auth-submit').textContent = 'Sign in'; $('#auth-code').focus(); return }
      await D.verifyCode(email, code); $('#auth-dialog').close(); await refreshAccount(); showView(); toast('Signed in');
    }catch(err){ $('#auth-error').textContent = err.message }
  };
  $('#name-form').onsubmit = async e => {
    e.preventDefault();
    const name = $('#username').value.trim().toLowerCase();
    if(!/^[a-z0-9_]{3,20}$/.test(name)){ $('#name-error').textContent = '3 to 20 lowercase letters, numbers or underscores.'; return }
    try{ await D.saveUsername(name); $('#name-dialog').close(); await refreshAccount(); toast('Welcome, ' + name) }
    catch(err){ $('#name-error').textContent = /duplicate|unique|taken/i.test(err.message) ? 'That username is taken.' : err.message }
  };

  /* ---------- Play ---------- */
  function triInput(f, pred, open){
    const p = pred ? [pred.p_home, pred.p_draw, pred.p_away] : [Math.round(f.lab_home * 100) || 34, Math.round(f.lab_draw * 100) || 33, 0];
    if(!pred) p[2] = 100 - p[0] - p[1];
    const labA = Math.round((f.lab_home ?? 1 / 3) * 100), labB = labA + Math.round((f.lab_draw ?? 1 / 3) * 100);
    return `<div class="tri${open ? '' : ' locked'}" data-id="${esc(f.id)}" data-h="${p[0]}" data-d="${p[1]}" role="group" aria-label="Your probabilities for ${esc(f.home)} v ${esc(f.away)}">
      <div class="seg-h" style="flex-basis:${p[0]}%">${p[0] >= 9 ? p[0] + '%' : ''}</div><div class="seg-d" style="flex-basis:${p[1]}%">${p[1] >= 9 ? p[1] + '%' : ''}</div><div class="seg-a" style="flex-basis:${p[2]}%">${p[2] >= 9 ? p[2] + '%' : ''}</div>
      <span class="lab" style="left:${labA}%" title="Lab"></span><span class="lab" style="left:${labB}%" title="Lab"></span>
      ${open ? `<span class="handle" data-k="0" tabindex="0" role="slider" aria-label="Home win chance" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${p[0]}" style="left:${p[0]}%"></span>
      <span class="handle" data-k="1" tabindex="0" role="slider" aria-label="Home or draw chance" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${p[0] + p[1]}" style="left:${p[0] + p[1]}%"></span>` : ''}
    </div>
    <div class="tri-labels"><span>Home <b>${p[0]}%</b></span><span>Draw <b>${p[1]}%</b></span><span>Away <b>${p[2]}%</b></span></div>
    <div class="tri-labels"><i>Lab: ${labA}% · ${labB - labA}% · ${100 - labB}%</i>${pred ? '' : '<i>Not saved yet</i>'}</div>`;
  }
  function setTri(el, h, d){
    h = Math.max(0, Math.min(100, Math.round(h))); d = Math.max(0, Math.min(100 - h, Math.round(d)));
    const a = 100 - h - d, segs = el.children;
    el.dataset.h = h; el.dataset.d = d;
    [h, d, a].forEach((v, i) => { segs[i].style.flexBasis = v + '%'; segs[i].textContent = v >= 9 ? v + '%' : '' });
    const handles = el.querySelectorAll('.handle');
    handles[0].style.left = h + '%'; handles[0].setAttribute('aria-valuenow', h);
    handles[1].style.left = (h + d) + '%'; handles[1].setAttribute('aria-valuenow', h + d);
    const labels = el.nextElementSibling.querySelectorAll('b');
    [h, d, a].forEach((v, i) => labels[i].textContent = v + '%');
    queueSave(el);
  }
  const timers = {};
  function queueSave(el){
    const id = el.dataset.id;
    if(!D.user()){ $('#auth-dialog').showModal(); return }
    clearTimeout(timers[id]);
    timers[id] = setTimeout(async () => {
      const h = +el.dataset.h, d = +el.dataset.d;
      try{
        await D.savePrediction(id, h, d, 100 - h - d);
        state.preds[id] = {p_home: h, p_draw: d, p_away: 100 - h - d};
        const s = document.querySelector(`[data-saved="${CSS.escape(id)}"]`); if(s){ s.classList.add('on'); setTimeout(() => s.classList.remove('on'), 1600) }
        renderMe();
      }catch(err){ toast(err.message) }
    }, 500);
  }
  function bindTri(root){
    root.querySelectorAll('.tri:not(.locked)').forEach(el => {
      const rect = () => el.getBoundingClientRect();
      const move = (k, clientX) => {
        const x = Math.round((clientX - rect().left) / rect().width * 100), h = +el.dataset.h, d = +el.dataset.d;
        if(k === 0) setTri(el, Math.min(x, h + d), h + d - Math.min(Math.max(x, 0), h + d));
        else setTri(el, h, Math.max(x, h) - h);
      };
      el.querySelectorAll('.handle').forEach(hd => {
        const k = +hd.dataset.k;
        hd.addEventListener('pointerdown', e => {
          if(!D.user()){ $('#auth-dialog').showModal(); return }
          hd.setPointerCapture(e.pointerId); hd.classList.add('drag');
          const mv = ev => move(k, ev.clientX);
          const up = () => { hd.classList.remove('drag'); hd.removeEventListener('pointermove', mv); hd.removeEventListener('pointerup', up) };
          hd.addEventListener('pointermove', mv); hd.addEventListener('pointerup', up);
        });
        hd.addEventListener('keydown', e => {
          const step = e.shiftKey ? 5 : 1, dir = e.key === 'ArrowRight' || e.key === 'ArrowUp' ? step : e.key === 'ArrowLeft' || e.key === 'ArrowDown' ? -step : 0;
          if(!dir) return; e.preventDefault();
          const h = +el.dataset.h, d = +el.dataset.d;
          if(k === 0){ const nh = Math.max(0, Math.min(h + d, h + dir)); setTri(el, nh, h + d - nh) } else setTri(el, h, Math.max(0, Math.min(100 - h, d + dir)));
        });
      });
      // Clicking the bar moves the nearer handle there.
      el.addEventListener('pointerdown', e => {
        if(e.target.classList.contains('handle')) return;
        const x = (e.clientX - rect().left) / rect().width * 100, h = +el.dataset.h, d = +el.dataset.d;
        move(Math.abs(x - h) <= Math.abs(x - h - d) ? 0 : 1, e.clientX);
      });
    });
  }
  function lockText(f){
    const t = M.lockTime(f), ms = t - Date.now();
    if(!M.isOpen(f)) return '<span class="locked">Locked</span>';
    if(ms < 864e5){ const h = Math.floor(ms / 36e5), m = Math.floor(ms % 36e5 / 6e4); return `<span class="locked">Locks in ${h}h ${m}m</span>` }
    return 'Locks ' + t.toLocaleString(undefined, {weekday: 'short', hour: '2-digit', minute: '2-digit'});
  }
  async function renderPlay(){
    const all = await D.fixtures(isoDay(-1), isoDay(14));
    state.fixtures = all.filter(f => f.status === 'scheduled');
    const ids = state.fixtures.map(f => f.id);
    const [preds, counts] = await Promise.all([D.myPredictions(ids), D.entryCounts(ids)]);
    state.preds = preds;
    const leagues = [...new Map(state.fixtures.map(f => [f.league_id, f.league_name])).entries()];
    $('#league-filter').innerHTML = [['all', 'All']].concat(leagues).map(([id, n]) => `<button data-league="${esc(id)}" aria-pressed="${state.league === id}">${esc(n)}</button>`).join('');
    const list = state.fixtures.filter(f => state.league === 'all' || f.league_id === state.league);
    $('#round-label').textContent = `${list.length} matches open`;
    let html = '', last = null;
    list.forEach((f, i) => {
      if(f.kickoff_date !== last){ html += `<div class="day">${esc(dayLabel(f.kickoff_date))}</div>`; last = f.kickoff_date }
      const open = M.isOpen(f);
      html += `<div class="card fixture" style="--i:${Math.min(i, 20)}"><div class="teams"><div class="team">${crest(f.home)}<span>${esc(f.home)}</span></div><div class="team">${crest(f.away)}<span>${esc(f.away)}</span></div></div>
        <div>${triInput(f, preds[f.id], open)}</div>
        <div class="meta">${esc(f.league_name)}<br>${lockText(f)}<br>${counts[f.id] || 0} player${counts[f.id] === 1 ? '' : 's'} in<br><span class="saved" data-saved="${esc(f.id)}">Saved ✓</span></div></div>`;
    });
    $('#fixtures').innerHTML = html || '<div class="card empty">No open fixtures right now. New rounds appear as soon as fixtures are published.</div>';
    bindTri($('#fixtures'));
    renderMe();
  }
  $('#league-filter').onclick = e => { const b = e.target.closest('[data-league]'); if(b){ state.league = b.dataset.league; store.set('btl-league', state.league); renderPlay() } };

  async function renderMe(){
    const card = $('#me-card');
    if(!D.user()){ card.innerHTML = `<h4>Your season</h4><div class="big">Join in</div><p class="sub">Free to play. Sign in with your email to save picks and climb the table.</p><button class="primary" id="me-join" type="button">Sign in to play</button>`;
      $('#me-join').onclick = () => $('#account').click(); return }
    const [mine, streak, board] = await Promise.all([D.myPoints(), D.myStreak(), D.leaderboard('2026-27')]);
    const total = mine.reduce((s, r) => s + Number(r.points), 0), rank = board.findIndex(r => r.user_id === D.user().id) + 1;
    const open = Object.keys(state.preds).length;
    card.innerHTML = `<h4>Your season</h4><div class="big ${total >= 0 ? 'pos' : 'neg'}" id="me-total">${pts(total)}</div><div class="sub">points vs the Lab</div>
      <div class="grid"><div><small>Rank</small><b>${rank ? '#' + rank : '–'}</b></div><div><small>Streak</small><b>${streak} wk</b></div><div><small>Picks open</small><b>${open}</b></div></div>`;
    if(!renderMe.done){ countUp($('#me-total'), total); renderMe.done = true }
  }

  /* ---------- Leaderboard ---------- */
  $('#board-scope').onclick = e => { const b = e.target.closest('[data-scope]'); if(!b) return; state.scope = b.dataset.scope; $$('#board-scope button').forEach(x => x.setAttribute('aria-pressed', x === b)); renderBoard() };
  $('#group-pick').onchange = e => { state.group = e.target.value; renderBoard() };
  async function renderBoard(){
    const box = $('#board');
    let rows;
    $('#group-pick').hidden = state.scope !== 'group';
    if(state.scope === 'week'){ const r = await D.latestRound(); rows = r ? await D.weekly(r) : [] }
    else rows = await D.leaderboard('2026-27');
    if(state.scope === 'group'){
      state.groups = D.user() ? await D.groups() : [];
      if(!state.groups.length){ box.innerHTML = '<div class="empty">Join or start a private league in the Leagues tab.</div>'; return }
      $('#group-pick').innerHTML = state.groups.map(g => `<option value="${esc(g.id)}">${esc(g.name)}</option>`).join('');
      if(!state.groups.some(g => g.id === state.group)) state.group = state.groups[0].id;
      $('#group-pick').value = state.group;
      const members = new Set(state.groups.find(g => g.id === state.group).members);
      rows = rows.filter(r => members.has(r.user_id));
    }
    if(!rows.length){ box.innerHTML = '<div class="empty">No finished matches scored yet.</div>'; return }
    const me = D.user() && D.user().id;
    const html = `<table class="board"><tr><th></th><th>Player</th><th style="text-align:right">Matches</th><th style="text-align:right">Beat the Lab</th><th style="text-align:right">Top pick right</th><th style="text-align:right">Points</th></tr>` +
      rows.map((r, i) => `<tr data-u="${esc(r.user_id)}" class="${r.user_id === me ? 'me' : ''}"><td class="rank">${i + 1}</td><td><b>${esc(r.username)}</b></td><td class="r">${r.predictions}</td>
        <td class="r">${r.beat_lab ?? '–'}</td><td class="r">${r.hit_rate != null ? Math.round(r.hit_rate * 100) + '%' : '–'}</td><td class="r ${r.points >= 0 ? 'pos' : 'neg'}">${pts(r.points)}</td></tr>`).join('') + '</table>';
    const before = new Map(); if(motionOK()) box.querySelectorAll('tr[data-u]').forEach(tr => before.set(tr.dataset.u, tr.getBoundingClientRect().top));
    box.innerHTML = html;
    box.querySelectorAll('tr[data-u]').forEach((tr, i) => {
      const top = before.get(tr.dataset.u);
      if(top !== undefined){ const dy = top - tr.getBoundingClientRect().top; if(dy) tr.animate([{transform: `translateY(${dy}px)`}, {transform: 'none'}], {duration: 450, easing: 'cubic-bezier(.2,.8,.2,1)'}) }
      else if(motionOK()) tr.animate([{opacity: 0, transform: 'translateX(-6px)'}, {opacity: 1, transform: 'none'}], {duration: 350, delay: Math.min(i, 20) * 25, fill: 'backwards'});
    });
  }

  /* ---------- Results ---------- */
  const BADGES = {upset_caller: ['🎯', 'Upset caller', 'Backed an outcome the Lab gave under 25%, and it happened'],
    bang_on: ['💯', 'Bang on', '80% or more on the actual result'], sharp_week: ['⚡', 'Sharp week', 'Beat the Lab over a round of 5+ picks']};
  async function renderResults(){
    if(!D.user()){ $('#my-stats').innerHTML = ''; $('#badges').innerHTML = ''; $('#history').innerHTML = '<div class="card empty">Sign in to see your results.</div>'; return }
    const [rows, badges, streak] = await Promise.all([D.myPoints(), D.myBadges(), D.myStreak()]);
    const crowd = await D.crowd(rows.map(r => r.fixture_id));
    const total = rows.reduce((s, r) => s + Number(r.points), 0), beat = rows.filter(r => r.points > 0).length;
    $('#my-stats').innerHTML = [['Points', `<span class="${total >= 0 ? 'pos' : 'neg'}" id="res-total">${pts(total)}</span>`], ['Matches scored', rows.length],
      ['Beat the Lab', rows.length ? Math.round(beat / rows.length * 100) + '%' : '–'], ['Weekly streak', streak]].map(([k, v]) => `<div class="card"><small>${k}</small><b>${v}</b></div>`).join('');
    if(rows.length) countUp($('#res-total'), total);
    const counts = {}; badges.forEach(b => counts[b.badge] = (counts[b.badge] || 0) + 1);
    $('#badges').innerHTML = Object.keys(counts).length ? `<div class="badges">${Object.entries(counts).map(([k, n], i) => { const [ico, name, why] = BADGES[k] || ['🏅', k, '']; return `<div class="badge" style="--i:${i}"><i>${ico}</i><div><b>${esc(name)}${n > 1 ? ' ×' + n : ''}</b><small>${esc(why)}</small></div></div>` }).join('')}</div>` : '';
    const pctRow = (label, a, hit) => `<span>${label}</span>${a.map((x, i) => `<b class="${i === hit ? 'hit' : ''}">${Math.round(x)}%</b>`).join('')}`;
    $('#history').innerHTML = rows.map((r, i) => { const f = r.fixture, c = crowd[r.fixture_id], o = M.outcome(f);
      return `<div class="card result" style="animation:rise .4s both;animation-delay:${Math.min(i, 15) * 30}ms"><div class="teams"><div class="team">${crest(f.home)}<span>${esc(f.home)}</span></div><div class="team">${crest(f.away)}<span>${esc(f.away)}</span></div></div>
        <div class="score">${f.home_goals}–${f.away_goals}</div>
        <div class="mini"><span></span><span>H</span><span>D</span><span>A</span>${pctRow('You', [r.p_home, r.p_draw, r.p_away], o)}${pctRow('Lab', [f.lab_home * 100, f.lab_draw * 100, f.lab_away * 100], o)}${c ? pctRow('Crowd', [c.p_home, c.p_draw, c.p_away], o) : ''}</div>
        <div class="pts ${r.points >= 0 ? 'pos' : 'neg'}">${pts(r.points)}</div></div>` }).join('') || '<div class="card empty">No finished matches yet. Make some picks and check back after the weekend.</div>';
  }

  /* ---------- Leagues ---------- */
  async function renderGroups(){
    if(!D.user()){ $('#my-groups').innerHTML = '<div class="card empty">Sign in to start or join a private league.</div>'; return }
    state.groups = await D.groups();
    $('#my-groups').innerHTML = state.groups.map(g => `<div class="card group"><div><b>${esc(g.name)}</b><div class="note">${g.members.length} member${g.members.length === 1 ? '' : 's'}</div></div>
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><span class="code">${esc(g.invite_code)}</span><button class="ghost" data-copy="${esc(g.invite_code)}" type="button">Copy invite</button><button class="ghost" data-leave="${esc(g.id)}" type="button">Leave</button></div></div>`).join('');
  }
  $('#my-groups').onclick = async e => {
    const c = e.target.closest('[data-copy]'), l = e.target.closest('[data-leave]');
    if(c){ const text = `Join my Beat the Lab league with code ${c.dataset.copy}: ${location.origin + location.pathname}#leagues`; try{ await navigator.clipboard.writeText(text); toast('Invite copied') }catch{ prompt('Copy this invite', text) } }
    if(l && confirm('Leave this league?')){ await D.leaveGroup(l.dataset.leave); renderGroups() }
  };
  $('#create-group').onsubmit = async e => { e.preventDefault(); if(!D.user()) return $('#account').click();
    try{ await D.createGroup($('#group-name').value.trim()); $('#group-name').value = ''; toast('League created'); renderGroups() }catch(err){ toast(err.message) } };
  $('#join-group').onsubmit = async e => { e.preventDefault(); if(!D.user()) return $('#account').click();
    try{ await D.joinGroup($('#group-code').value); $('#group-code').value = ''; toast('Joined'); renderGroups() }catch(err){ toast(err.message) } };

  (async () => { await D.init(async () => { await refreshAccount(); showView() }); await refreshAccount(); showView() })();
})();
