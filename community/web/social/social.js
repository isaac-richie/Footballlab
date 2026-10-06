(function(){
  'use strict';
  const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const code6 = () => Array.from({length: 6}, () => 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'[Math.floor(Math.random() * 32)]).join('');
  const hue = s => { let h = 0; for(const c of String(s)) h = (h * 31 + c.charCodeAt(0)) % 360; return h };
  const av = name => `<span class="av" style="background:hsl(${hue(name)} 55% 42%)" aria-hidden="true">${esc(String(name || '?').slice(0, 2).toUpperCase())}</span>`;
  const when = t => { const d = new Date(t), s = (Date.now() - d) / 1000; return s < 60 ? 'now' : s < 3600 ? Math.floor(s / 60) + 'm' : s < 86400 ? Math.floor(s / 3600) + 'h' : d.toLocaleDateString() };
  function toast(msg){ const t = $('#toast'); t.textContent = msg; t.classList.add('on'); clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove('on'), 2600) }

  /* ======================= Data: Supabase ======================= */
  function supabaseApi(cfg){
    const sb = window.supabase.createClient(cfg.supabaseUrl, cfg.supabaseAnonKey);
    let session = null, me = null;
    const must = r => { if(r.error) throw new Error(r.error.message); return r.data };
    const uid = () => session && session.user.id;
    return {
      demo: false,
      async init(onAuth){ session = must(await sb.auth.getSession()).session; sb.auth.onAuthStateChange((_e, s) => { session = s; me = null; onAuth() }) },
      signedIn: () => !!session,
      async sendCode(email){ must(await sb.auth.signInWithOtp({email, options: {shouldCreateUser: true}})) },
      async verifyCode(email, token){ session = must(await sb.auth.verifyOtp({email, token, type: 'email'})).session },
      async signOut(){ await sb.auth.signOut(); session = null; me = null },
      async me(){
        if(!uid()) return null; if(me) return me;
        const p = must(await sb.from('profiles').select('id,username').eq('id', uid()).maybeSingle()); if(!p) return null;
        const [mod, ban] = await Promise.all([sb.rpc('is_moderator', {u: uid()}), sb.from('bans').select('until,reason').eq('user_id', uid()).maybeSingle()]);
        me = {...p, moderator: !!mod.data, ban: ban.data && new Date(ban.data.until) > new Date() ? ban.data : null}; return me;
      },
      async createProfile(username){ must(await sb.from('profiles').insert({id: uid(), username, adult: true})); me = null },
      async rooms(){
        const rooms = must(await sb.from('rooms').select('id,kind,slug,title').order('created_at'));
        const dms = rooms.filter(r => r.kind === 'dm').map(r => r.id);
        if(dms.length){
          const others = must(await sb.from('room_members').select('room_id,user_id,profiles(username)').in('room_id', dms).neq('user_id', uid()));
          for(const r of rooms) if(r.kind === 'dm'){ const o = others.find(x => x.room_id === r.id); r.title = o && o.profiles ? o.profiles.username : 'Former friend'; r.other = o && o.user_id }
        }
        return rooms;
      },
      async messages(room){
        const rows = must(await sb.from('messages').select('id,room_id,author,body,created_at,hidden,profiles!messages_author_fkey(username)').eq('room_id', room).order('created_at', {ascending: false}).limit(60));
        return rows.reverse().map(r => ({...r, username: r.profiles && r.profiles.username}));
      },
      subscribeRoom(room, onMsg){
        const ch = sb.channel('room-' + room).on('postgres_changes', {event: 'INSERT', schema: 'public', table: 'messages', filter: `room_id=eq.${room}`}, async ({new: m}) => {
          const p = must(await sb.from('profiles').select('username').eq('id', m.author).maybeSingle()); onMsg({...m, username: p && p.username});
        }).subscribe();
        return () => sb.removeChannel(ch);
      },
      watchMine(onEvent){
        const ch = sb.channel('mine-' + uid())
          .on('postgres_changes', {event: '*', schema: 'public', table: 'friend_requests', filter: `recipient=eq.${uid()}`}, () => onEvent('requests'))
          .on('postgres_changes', {event: '*', schema: 'public', table: 'friend_requests', filter: `sender=eq.${uid()}`}, () => onEvent('requests'))
          .on('postgres_changes', {event: 'INSERT', schema: 'public', table: 'challenges', filter: `recipient=eq.${uid()}`}, () => onEvent('challenge'))
          .subscribe();
        return () => sb.removeChannel(ch);
      },
      async send(room, body){ must(await sb.from('messages').insert({room_id: room, author: uid(), body})) },
      async report(message_id, reason, note){ must(await sb.from('reports').insert({reporter: uid(), message_id, reason, note: note || null})) },
      async block(user){ must(await sb.from('blocks').insert({blocker: uid(), blocked: user})) },
      async unblock(user){ must(await sb.from('blocks').delete().eq('blocker', uid()).eq('blocked', user)) },
      async blocked(){ const rows = must(await sb.from('blocks').select('blocked,profiles!blocks_blocked_fkey(username)').eq('blocker', uid())); return rows.map(r => ({id: r.blocked, username: r.profiles && r.profiles.username})) },
      async friends(){ return must(await sb.from('my_friends').select('*')).map(f => ({id: f.friend_id, username: f.username})) },
      async requests(){
        const rows = must(await sb.from('friend_requests').select('sender,recipient,status,created_at,s:profiles!friend_requests_sender_fkey(username),r:profiles!friend_requests_recipient_fkey(username)').eq('status', 'pending'));
        return {incoming: rows.filter(r => r.recipient === uid()).map(r => ({id: r.sender, username: r.s && r.s.username})),
                outgoing: rows.filter(r => r.sender === uid()).map(r => ({id: r.recipient, username: r.r && r.r.username}))};
      },
      async addFriend(username){
        const p = must(await sb.from('profiles').select('id').eq('username', username).maybeSingle());
        if(!p) throw new Error('No player with that username.'); if(p.id === uid()) throw new Error("That's you!");
        must(await sb.from('friend_requests').insert({sender: uid(), recipient: p.id}));
      },
      async respond(sender, accept){ must(await sb.from('friend_requests').update({status: accept ? 'accepted' : 'declined', responded_at: new Date().toISOString()}).eq('sender', sender).eq('recipient', uid())) },
      async unfriend(other){ must(await sb.from('friend_requests').delete().or(`and(sender.eq.${uid()},recipient.eq.${other}),and(sender.eq.${other},recipient.eq.${uid()})`)) },
      async openDm(friend){ return must(await sb.rpc('open_dm', {friend})) },
      async challenges(){
        const rows = must(await sb.from('challenges').select('id,sender,recipient,game,mode,room_code,status,expires_at,s:profiles!challenges_sender_fkey(username),r:profiles!challenges_recipient_fkey(username)').eq('status', 'pending').gt('expires_at', new Date().toISOString()));
        return rows.map(r => ({...r, from: r.s && r.s.username, to: r.r && r.r.username, incoming: r.recipient === uid()}));
      },
      async challenge(friend, mode){ const room_code = code6(); must(await sb.from('challenges').insert({sender: uid(), recipient: friend, game: 'kickabout', mode, room_code})); return room_code },
      async answer(id, accept){ must(await sb.from('challenges').update({status: accept ? 'accepted' : 'declined'}).eq('id', id)) },
      async moderate(id, hide){ must(await sb.rpc('moderate_message', {msg: id, hide, reason: hide ? 'moderator' : null})) },
    };
  }

  /* ======================= Data: demo (in memory) ======================= */
  function demoApi(){
    const ids = {me: 'me', ada: 'u1', ben: 'u2', cyd: 'u3', dee: 'u4'};
    const names = {me: 'you', u1: 'ada', u2: 'ben', u3: 'cyd', u4: 'dee'};
    const pub = ['General', 'Premier League', 'La Liga', 'Serie A', 'Bundesliga', 'Ligue 1', 'Kickabout', 'Spot Kick'].map((t, i) => ({id: 'r' + i, kind: 'public', slug: t.toLowerCase().replace(/ /g, '-'), title: t}));
    const rooms = [...pub];
    const ago = m => new Date(Date.now() - m * 60000).toISOString();
    let msgId = 1;
    const messages = [
      {room_id: 'r0', author: 'u1', body: 'Who else thinks the Lab is sleeping on Brighton this weekend?', created_at: ago(42)},
      {room_id: 'r0', author: 'u2', body: 'Lab gave Arsenal 66%. I went 75. Free points 😏', created_at: ago(30)},
      {room_id: 'r0', author: 'u3', body: 'Anyone up for a 3v3 Kickabout later?', created_at: ago(12)},
      {room_id: 'r1', author: 'u4', body: 'City to drop points at least once in October. Calling it.', created_at: ago(55)},
      {room_id: 'r6', author: 'u2', body: 'Tip: pass early in 11v11, the AI presses hard.', created_at: ago(90)},
    ].map(m => ({...m, id: msgId++, hidden: false}));
    const friends = new Set(['u2']), incoming = new Set(['u3']), outgoing = new Set(), blocked = new Set();
    const challenges = [{id: 'c1', sender: 'u2', recipient: 'me', game: 'kickabout', mode: '5v5', room_code: 'BEN123', status: 'pending', expires_at: new Date(Date.now() + 9e5).toISOString()}];
    const subs = new Map(); let mineCb = () => {};
    const BANTER = ['Bold call 😂', 'The Lab disagrees, respectfully', 'Screenshot this for later', 'Ref! 😤', 'We go again 🔁'];
    const deliver = m => { messages.push(m); (subs.get(m.room_id) || []).forEach(f => f({...m, username: names[m.author]})) };
    const wait = v => new Promise(r => setTimeout(() => r(v), 80));
    return {
      demo: true,
      async init(){}, signedIn: () => true,
      async me(){ return {id: 'me', username: 'you', moderator: true, ban: null} },
      async rooms(){ return wait(rooms.map(r => r.kind === 'dm' ? {...r, title: names[r.other]} : r)) },
      async messages(room){ return wait(messages.filter(m => m.room_id === room && !blocked.has(m.author)).slice(-60).map(m => ({...m, username: names[m.author]}))) },
      subscribeRoom(room, f){ subs.set(room, [f]); return () => subs.delete(room) },
      watchMine(f){ mineCb = f; return () => {} },
      async send(room, body){
        const recent = messages.filter(m => m.author === 'me' && Date.now() - new Date(m.created_at) < 10000).length;
        if(recent >= 5) throw new Error('Slow down: too many messages');
        deliver({id: msgId++, room_id: room, author: 'me', body: body.replace(/\b(f+u+c+k+\w*|sh[i1]t\w*)\b/gi, '****'), created_at: new Date().toISOString(), hidden: false});
        const r = rooms.find(x => x.id === room);
        const replier = r.kind === 'dm' ? r.other : ['u1', 'u2', 'u3', 'u4'].filter(u => !blocked.has(u))[Math.floor(Math.random() * 3)];
        if(replier && !blocked.has(replier)) setTimeout(() => deliver({id: msgId++, room_id: room, author: replier, body: BANTER[Math.floor(Math.random() * BANTER.length)], created_at: new Date().toISOString(), hidden: false}), 1800);
      },
      async report(){ await wait() },
      async block(u){ blocked.add(u); friends.delete(u); incoming.delete(u); outgoing.delete(u); await wait() },
      async unblock(u){ blocked.delete(u); await wait() },
      async blocked(){ return [...blocked].map(id => ({id, username: names[id]})) },
      async friends(){ return [...friends].map(id => ({id, username: names[id]})) },
      async requests(){ return {incoming: [...incoming].map(id => ({id, username: names[id]})), outgoing: [...outgoing].map(id => ({id, username: names[id]}))} },
      async addFriend(username){
        const id = Object.keys(names).find(k => names[k] === username);
        if(!id) throw new Error('No player with that username. Try ada or dee.'); if(id === 'me') throw new Error("That's you!");
        if(blocked.has(id)) throw new Error('Unblock them first.');
        outgoing.add(id); setTimeout(() => { if(outgoing.delete(id)){ friends.add(id); toast(`${username} accepted your request`); mineCb('requests') } }, 2500);
      },
      async respond(id, accept){ incoming.delete(id); if(accept) friends.add(id) },
      async unfriend(id){ friends.delete(id); outgoing.delete(id) },
      async openDm(friend){ let r = rooms.find(x => x.kind === 'dm' && x.other === friend); if(!r){ r = {id: 'dm-' + friend, kind: 'dm', title: names[friend], other: friend}; rooms.push(r) } return r.id },
      async challenges(){ return challenges.filter(c => c.status === 'pending' && new Date(c.expires_at) > new Date()).map(c => ({...c, from: names[c.sender], to: names[c.recipient], incoming: c.recipient === 'me'})) },
      async challenge(friend, mode){ const room_code = code6(); challenges.push({id: 'c' + Date.now(), sender: 'me', recipient: friend, game: 'kickabout', mode, room_code, status: 'pending', expires_at: new Date(Date.now() + 9e5).toISOString()}); return room_code },
      async answer(id, accept){ const c = challenges.find(x => x.id === id); if(c) c.status = accept ? 'accepted' : 'declined' },
      async moderate(id, hide){ const m = messages.find(x => x.id === id); if(m) m.hidden = hide },
    };
  }

  /* ======================= UI ======================= */
  const cfg = window.LEAGUE_CONFIG || {};
  let D = null;
  const state = {room: null, rooms: [], unsub: null, me: null, chMode: '5v5', chFriend: null, reportId: null};

  async function boot(){
    if(cfg.supabaseUrl && cfg.supabaseAnonKey){
      await new Promise((ok, fail) => { const s = document.createElement('script'); s.src = 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/dist/umd/supabase.min.js'; s.onload = ok; s.onerror = fail; document.head.appendChild(s) });
      D = supabaseApi(cfg);
    } else D = demoApi();
    await D.init(() => start());
    start();
  }
  async function start(){
    $('#notice').innerHTML = D.demo ? '<div class="banner">Demo mode: sample players and messages on this device only. Connect Supabase in config.js to go live.</div>' : '';
    if(!D.signedIn()){ $('#account').textContent = 'Sign in'; $('#stream').innerHTML = '<div class="empty-s">Sign in to join the conversation. Terrace is for adults (18+).</div>'; $('#composer').hidden = true; return }
    state.me = await D.me();
    if(!state.me){ $('#profile-dlg').showModal(); return }
    $('#account').textContent = '@' + state.me.username;
    if(state.me.ban){ $('#notice').innerHTML += `<div class="banner">Your account is suspended until ${esc(new Date(state.me.ban.until).toLocaleString())}: ${esc(state.me.ban.reason)}.</div>`; $('#composer').hidden = true }
    else $('#composer').hidden = false;
    await loadRooms();
    if(!state.room) openRoom(state.rooms.find(r => r.slug === 'general') || state.rooms[0]);
    refreshSide();
    D.watchMine(kind => { refreshSide(); if(kind === 'challenge') toast('New challenge!') });
  }

  async function loadRooms(){
    state.rooms = await D.rooms();
    const item = r => `<li><button data-room="${esc(r.id)}" aria-current="${state.room === r.id}">${r.kind === 'dm' ? av(r.title) : '<span class="hash">#</span>'}${esc(r.title)}</button></li>`;
    $('#public-rooms').innerHTML = state.rooms.filter(r => r.kind === 'public').map(item).join('');
    const dms = state.rooms.filter(r => r.kind === 'dm');
    $('#dm-rooms').innerHTML = dms.length ? dms.map(item).join('') : '<li class="empty-s">Message a friend from the Friends panel.</li>';
  }
  document.addEventListener('click', e => { const b = e.target.closest('[data-room]'); if(b){ openRoom(state.rooms.find(r => r.id === b.dataset.room)); pane('chat') } });

  async function openRoom(room){
    if(!room) return;
    if(state.unsub) state.unsub();
    state.room = room.id;
    $$('[data-room]').forEach(b => b.setAttribute('aria-current', String(b.dataset.room === room.id)));
    $('#room-title').textContent = room.kind === 'dm' ? room.title : '# ' + room.title;
    $('#room-rules').textContent = room.kind === 'dm' ? 'Only you two can see this. Blocking ends the conversation.' : 'Be decent. No hate, scams, or sharing personal details. Report anything that isn\'t.';
    const list = await D.messages(room.id);
    if(state.room !== room.id) return;
    $('#stream').innerHTML = list.length ? list.map(msgHtml).join('') : '<div class="empty-s">No messages yet. Start the banter.</div>';
    scrollEnd();
    state.unsub = D.subscribeRoom(room.id, m => { if(state.room !== room.id) return; $('.stream .empty-s') && $('.stream .empty-s').remove(); $('#stream').insertAdjacentHTML('beforeend', msgHtml(m)); scrollEnd() });
  }
  const scrollEnd = () => { const s = $('#stream'); s.scrollTop = s.scrollHeight };
  function msgHtml(m){
    const mine = state.me && m.author === state.me.id, mod = state.me && state.me.moderator;
    const acts = [!mine && `<button data-act="report" data-id="${m.id}">Report</button>`, !mine && `<button data-act="block" data-user="${esc(m.author)}" data-name="${esc(m.username)}">Block</button>`,
      mod && `<button data-act="${m.hidden ? 'unhide' : 'hide'}" data-id="${m.id}">${m.hidden ? 'Unhide' : 'Hide'}</button>`].filter(Boolean).join('');
    return `<div class="m${m.hidden ? ' hidden' : ''}" data-mid="${m.id}">${av(m.username)}<div class="body"><div class="mmeta"><b>${esc(m.username || 'player')}</b>${when(m.created_at)}${m.hidden ? ' · hidden' : ''}</div><div class="text">${esc(m.body)}</div></div>${acts ? `<div class="acts">${acts}</div>` : ''}</div>`;
  }
  $('#composer').onsubmit = async e => {
    e.preventDefault(); const t = $('#text'), body = t.value.trim(); if(!body) return;
    try{ await D.send(state.room, body.slice(0, 500)); t.value = '' }catch(err){ toast(/policy|permission/i.test(err.message) ? "You can't post here." : err.message) }
  };
  $('#text').addEventListener('keydown', e => { if(e.key === 'Enter' && !e.shiftKey){ e.preventDefault(); $('#composer').requestSubmit() } });

  // Message actions
  $('#stream').addEventListener('click', async e => {
    const b = e.target.closest('[data-act]'); if(!b) return;
    if(b.dataset.act === 'report'){ state.reportId = +b.dataset.id || b.dataset.id; $('#report-note').value = ''; $('#report-dlg').showModal() }
    else if(b.dataset.act === 'block'){ if(confirm(`Block ${b.dataset.name}? You won't see each other's messages, and they can't message or friend you.`)){ await D.block(b.dataset.user); toast('Blocked'); await refreshSide(); openRoom(state.rooms.find(r => r.id === state.room)) } }
    else if(b.dataset.act === 'hide' || b.dataset.act === 'unhide'){ await D.moderate(+b.dataset.id || b.dataset.id, b.dataset.act === 'hide'); openRoom(state.rooms.find(r => r.id === state.room)) }
  });
  $('#report-form').addEventListener('submit', async e => {
    if(e.submitter && e.submitter.value === 'cancel') return;
    try{ await D.report(state.reportId, $('#report-reason').value, $('#report-note').value.trim()); toast('Report sent. Thank you.') }
    catch(err){ toast(/duplicate|unique/i.test(err.message) ? 'You already reported this.' : err.message) }
  });

  // Friends panel
  async function refreshSide(){
    const [fr, rq, ch, bl] = await Promise.all([D.friends(), D.requests(), D.challenges(), D.blocked()]);
    $('#friends').innerHTML = fr.length ? fr.map(f => `<div class="frow">${av(f.username)}<span class="nm">${esc(f.username)}</span><button class="sbtn" data-dm="${esc(f.id)}">Message</button><button class="sbtn go" data-ch="${esc(f.id)}" data-name="${esc(f.username)}">Challenge</button><button class="sbtn" data-unfriend="${esc(f.id)}" title="Remove friend" aria-label="Remove ${esc(f.username)}">✕</button></div>`).join('') : '<div class="empty-s">No friends yet. Add someone by username.</div>';
    $('#requests').innerHTML = (rq.incoming.map(r => `<div class="frow">${av(r.username)}<span class="nm">${esc(r.username)}</span><button class="sbtn go" data-accept="${esc(r.id)}">Accept</button><button class="sbtn" data-decline="${esc(r.id)}">Decline</button></div>`).join('') +
      rq.outgoing.map(r => `<div class="frow">${av(r.username)}<span class="nm">${esc(r.username)} <small class="note">sent</small></span><button class="sbtn" data-unfriend="${esc(r.id)}">Cancel</button></div>`).join('')) || '<div class="empty-s">No pending requests.</div>';
    $('#challenges').innerHTML = ch.map(c => c.incoming
      ? `<div class="frow">${av(c.from)}<span class="nm">${esc(c.from)} · ${esc(c.mode)}</span><button class="sbtn go" data-play="${esc(c.id)}" data-code="${esc(c.room_code)}">Play</button><button class="sbtn" data-nope="${esc(c.id)}">No</button></div>`
      : `<div class="frow">${av(c.to)}<span class="nm">You → ${esc(c.to)} · ${esc(c.mode)}</span><a class="sbtn" href="../match/?host=${esc(c.room_code)}&mode=${esc(c.mode)}">Open</a></div>`).join('') || '<div class="empty-s">No open challenges.</div>';
    $('#blocked').innerHTML = bl.map(b => `<div class="frow"><span class="nm">${esc(b.username)}</span><button class="sbtn" data-unblock="${esc(b.id)}">Unblock</button></div>`).join('') || '<div class="empty-s">Nobody blocked.</div>';
    const nIn = rq.incoming.length, nCh = ch.filter(c => c.incoming).length;
    $('#badge-r').innerHTML = nIn ? `<span class="badge-n">${nIn}</span>` : ''; $('#badge-c').innerHTML = nCh ? `<span class="badge-n">${nCh}</span>` : '';
    $('#badge-m').innerHTML = nIn + nCh ? `<span class="badge-n">${nIn + nCh}</span>` : '';
  }
  $('.right').addEventListener('click', async e => {
    const t = e.target.closest('button'); if(!t) return;
    try{
      if(t.dataset.dm){ const room = await D.openDm(t.dataset.dm); await loadRooms(); openRoom(state.rooms.find(r => r.id === room)); pane('chat') }
      else if(t.dataset.ch){ state.chFriend = t.dataset.ch; $('#challenge-title').textContent = 'Challenge ' + t.dataset.name; $('#challenge-dlg').showModal() }
      else if(t.dataset.unfriend){ await D.unfriend(t.dataset.unfriend); refreshSide() }
      else if(t.dataset.accept){ await D.respond(t.dataset.accept, true); toast('Friend added'); refreshSide() }
      else if(t.dataset.decline){ await D.respond(t.dataset.decline, false); refreshSide() }
      else if(t.dataset.play){ await D.answer(t.dataset.play, true); location.href = `../match/?room=${encodeURIComponent(t.dataset.code)}&auto=1` }
      else if(t.dataset.nope){ await D.answer(t.dataset.nope, false); refreshSide() }
      else if(t.dataset.unblock){ await D.unblock(t.dataset.unblock); toast('Unblocked'); refreshSide() }
    }catch(err){ toast(err.message) }
  });
  $('#addf').onsubmit = async e => {
    e.preventDefault(); const n = $('#addname').value.trim().toLowerCase(); if(!n) return;
    try{ await D.addFriend(n); $('#addname').value = ''; toast('Request sent'); refreshSide() }
    catch(err){ toast(/duplicate|unique/i.test(err.message) ? 'Request already sent.' : /policy|permission/i.test(err.message) ? "You can't send them a request." : err.message) }
  };
  $$('#ch-mode button').forEach(b => b.onclick = () => { state.chMode = b.dataset.v; $$('#ch-mode button').forEach(x => x.setAttribute('aria-pressed', String(x === b))) });
  $('#challenge-dlg').addEventListener('close', async () => {
    if($('#challenge-dlg').returnValue !== 'ok') return;
    try{ const code = await D.challenge(state.chFriend, state.chMode); location.href = `../match/?host=${code}&mode=${state.chMode}` }catch(err){ toast(err.message) }
  });

  // Account
  $('#account').onclick = async () => {
    if(D.demo){ toast('Demo mode: you are signed in as "you".'); return }
    if(!D.signedIn()){ $('#otp-field').hidden = true; $('#auth-submit').textContent = 'Send code'; $('#auth-dlg').showModal(); return }
    if(confirm('Sign out?')){ await D.signOut(); location.reload() }
  };
  $('#auth-form').addEventListener('submit', async e => {
    if(e.submitter && e.submitter.value === 'cancel') return; e.preventDefault();
    const email = $('#auth-email').value.trim(), code = $('#auth-code').value.trim(); $('#auth-error').textContent = '';
    try{ if($('#otp-field').hidden){ await D.sendCode(email); $('#otp-field').hidden = false; $('#auth-submit').textContent = 'Sign in'; return } await D.verifyCode(email, code); $('#auth-dlg').close(); start() }
    catch(err){ $('#auth-error').textContent = err.message }
  });
  $('#profile-form').addEventListener('submit', async e => {
    e.preventDefault(); const n = $('#p-name').value.trim().toLowerCase();
    if(!/^[a-z0-9_]{3,20}$/.test(n)){ $('#p-error').textContent = '3 to 20 lowercase letters, numbers or underscores.'; return }
    if(!$('#p-adult').checked){ $('#p-error').textContent = 'Terrace is for adults (18+) only.'; return }
    try{ await D.createProfile(n); $('#profile-dlg').close(); start() }catch(err){ $('#p-error').textContent = /duplicate|unique/i.test(err.message) ? 'That username is taken.' : err.message }
  });

  // Mobile panes
  function pane(name){ const app = $('#app'); app.classList.toggle('show-side', name === 'side'); app.classList.toggle('show-right', name === 'right'); $$('.tabs-m button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.pane === name))) }
  $$('.tabs-m button').forEach(b => b.onclick = () => pane(b.dataset.pane));

  boot().catch(err => { $('#notice').innerHTML = `<div class="banner">Could not start: ${esc(err.message)}</div>` });
})();
