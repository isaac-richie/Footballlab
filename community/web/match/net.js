// Kickabout networking: host-authoritative, peer-to-peer.
// Signalling (the handshake) goes over Supabase Realtime when configured, otherwise over a
// BroadcastChannel so two tabs on one device can play. Game traffic then flows directly
// between the browsers over WebRTC data channels; if no direct path forms, it falls back to
// relaying through the signalling channel at a lower rate.
(function(root){
  'use strict';
  const ICE = [{urls: 'stun:stun.l.google.com:19302'}, {urls: 'stun:stun1.l.google.com:19302'}];
  const P2P_TIMEOUT = 9000;

  function signalling(room){
    const cfg = root.LEAGUE_CONFIG || {}, handlers = [];
    if(cfg.supabaseUrl && cfg.supabaseAnonKey && root.supabase){
      const sb = root.supabase.createClient(cfg.supabaseUrl, cfg.supabaseAnonKey);
      const ch = sb.channel('kickabout-' + room, {config: {broadcast: {self: false}}});
      ch.on('broadcast', {event: 'sig'}, ({payload}) => handlers.forEach(h => h(payload)));
      ch.subscribe();
      return {kind: 'online', send: msg => ch.send({type: 'broadcast', event: 'sig', payload: msg}), on: h => handlers.push(h), close: () => sb.removeChannel(ch)};
    }
    const bc = new BroadcastChannel('kickabout-' + room);
    bc.onmessage = e => handlers.forEach(h => h(e.data));
    return {kind: 'this device', send: msg => bc.postMessage(msg), on: h => handlers.push(h), close: () => bc.close()};
  }

  // Session descriptions must travel as plain objects: browsers refuse to clone the native type.
  const plain = d => ({type: d.type, sdp: d.sdp});
  const makeId = () => Math.random().toString(36).slice(2, 10);
  const roomCode = () => Array.from({length: 6}, () => 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'[Math.floor(Math.random() * 32)]).join('');

  // Returns {send(kind, msg), on(kind, fn), close(), status} where kind is 'game' or 'chat'.
  function connect(room, role, events = {}){
    const sig = signalling(room), me = makeId();
    const listeners = {game: [], chat: [], ctrl: []};
    const emit = (k, m) => listeners[k].forEach(f => f(m));
    const link = {status: 'waiting', via: null, signal: sig.kind, peer: null,
      on(k, f){ listeners[k].push(f) },
      send(k, msg){
        if(link.via === 'p2p'){ const ch = k === 'game' ? game : chat; if(ch && ch.readyState === 'open') ch.send(JSON.stringify(msg)) }
        else if(link.via === 'relay'){ if(k !== 'game' || Date.now() - lastRelay > 90){ if(k === 'game') lastRelay = Date.now(); sig.send({type: 'relay', from: me, k, msg}) } }
      },
      close(){ try{ sig.send({type: 'bye', from: me}) }catch{} try{ pc.close() }catch{} sig.close(); clearInterval(helloTimer); clearTimeout(fallback) }};
    let lastRelay = 0, game = null, chat = null, peerId = null, helloTimer = null, fallback = null;
    const pc = new RTCPeerConnection({iceServers: ICE});
    const pending = [];
    const setStatus = s => { link.status = s; (events.status || (() => {}))(s, link) };
    const wire = (ch, k) => {
      ch.onmessage = e => { try{ emit(k, JSON.parse(e.data)) }catch{} };
      ch.onopen = () => { if(game && game.readyState === 'open' && chat && chat.readyState === 'open'){ link.via = 'p2p'; clearTimeout(fallback); setStatus('connected') } };
    };
    pc.onicecandidate = e => { if(e.candidate && peerId) sig.send({type: 'ice', from: me, to: peerId, c: e.candidate.toJSON()}) };
    pc.onconnectionstatechange = () => { if(['failed', 'disconnected'].includes(pc.connectionState) && link.via === 'p2p'){ setStatus('lost') } };
    const startFallback = () => { fallback = setTimeout(() => { if(link.via !== 'p2p' && peerId){ link.via = 'relay'; setStatus('connected') } }, P2P_TIMEOUT) };

    if(role === 'host'){
      game = pc.createDataChannel('game', {ordered: false, maxRetransmits: 0}); chat = pc.createDataChannel('chat');
      wire(game, 'game'); wire(chat, 'chat');
    } else {
      pc.ondatachannel = e => { if(e.channel.label === 'game'){ game = e.channel; wire(game, 'game') } else { chat = e.channel; wire(chat, 'chat') } };
      const hello = () => sig.send({type: 'hello', from: me, name: events.name || 'Guest'});
      hello(); helloTimer = setInterval(() => { if(!peerId) hello() }, 1000);
    }
    sig.on(async msg => {
      if(!msg || msg.from === me) return;
      if(msg.to && msg.to !== me) return;
      try{
        if(msg.type === 'hello' && role === 'host'){
          if(peerId && peerId !== msg.from){ sig.send({type: 'full', from: me, to: msg.from}); return }
          if(peerId) return;
          peerId = msg.from; link.peer = msg.name || 'Guest'; setStatus('connecting');
          await pc.setLocalDescription(await pc.createOffer());
          sig.send({type: 'offer', from: me, to: peerId, sdp: plain(pc.localDescription), name: events.name || 'Host'});
          startFallback();
        } else if(msg.type === 'offer' && role === 'guest' && !peerId){
          peerId = msg.from; link.peer = msg.name || 'Host'; clearInterval(helloTimer); setStatus('connecting');
          await pc.setRemoteDescription(msg.sdp);
          await pc.setLocalDescription(await pc.createAnswer());
          sig.send({type: 'answer', from: me, to: peerId, sdp: plain(pc.localDescription)});
          while(pending.length) await pc.addIceCandidate(pending.shift());
          startFallback();
        } else if(msg.type === 'answer' && role === 'host' && msg.from === peerId){
          await pc.setRemoteDescription(msg.sdp);
          while(pending.length) await pc.addIceCandidate(pending.shift());
        } else if(msg.type === 'ice' && msg.from === peerId){
          if(pc.remoteDescription) await pc.addIceCandidate(msg.c); else pending.push(msg.c);
        } else if(msg.type === 'relay' && msg.from === peerId && link.via === 'relay'){
          emit(msg.k, msg.msg);
        } else if(msg.type === 'full' && role === 'guest'){
          setStatus('full');
        } else if(msg.type === 'bye' && msg.from === peerId){
          setStatus('left');
        }
      }catch(err){ console.warn('kickabout signalling', err) }
    });
    setStatus(role === 'host' ? 'waiting' : 'joining');
    return link;
  }

  root.KickNet = {connect, roomCode, signalling};
})(typeof globalThis !== 'undefined' ? globalThis : this);
