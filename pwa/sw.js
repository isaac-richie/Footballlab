/* Fairline service worker: makes the app installable and lets the shell open offline.
   Pages are network-first (the latest page always wins; the last good copy is the offline
   fallback). Data (/api/...) is never cached, so odds and forecasts are always live. */
const SHELL = 'fl-shell-v2';         // v2: Fairline icons
const STATIC = ['/icons/icon-192.png', '/icons/icon-512.png', '/manifest.webmanifest'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(SHELL).then(c => c.addAll(STATIC)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== SHELL).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  const req = e.request, url = new URL(req.url);
  if(req.method !== 'GET' || url.origin !== location.origin || url.pathname.startsWith('/api/')) return;
  if(req.mode === 'navigate'){
    e.respondWith(fetch(req).then(res => {
      if(res.ok){ const copy = res.clone(); caches.open(SHELL).then(c => c.put('/', copy)) }
      return res;
    }).catch(() => caches.match('/').then(r => r || new Response(
      '<!doctype html><meta name="viewport" content="width=device-width"><title>Fairline</title>' +
      '<body style="font:16px system-ui;background:#141210;color:#F2EDE4;padding:40px">You are offline. Fairline needs a connection for live odds and forecasts.</body>',
      {headers: {'Content-Type': 'text/html; charset=utf-8'}}))));
    return;
  }
  if(STATIC.includes(url.pathname)) e.respondWith(caches.match(req).then(r => r || fetch(req)));
});
