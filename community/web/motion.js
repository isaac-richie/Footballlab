/* Motion layer shared by every page (the welcome film is in welcome.js): 3D tilt cards, magnetic buttons,
   scroll reveal and sweeping headlines. Everything is skipped
   for prefers-reduced-motion and when the effects toggle is off; touch devices get no
   cursor or tilt. */
(function(){
  'use strict';
  const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
  const fine = matchMedia('(hover: hover) and (pointer: fine)').matches;
  const off = () => { try{ return localStorage.getItem('fx') === 'off' }catch{ return false } };
  const logoSrc = (document.querySelector('.logo-mark') || {}).src || '/logo-mark.svg';

  const css = document.createElement('style');
  css.textContent = `
  .tilt{transform-style:preserve-3d;will-change:transform;transition:transform .5s cubic-bezier(.2,.8,.2,1)}
  .tilt.on{transition:transform .08s linear}
  .tilt .glare{position:absolute;inset:0;border-radius:inherit;pointer-events:none;z-index:3;opacity:0;transition:opacity .3s;
    background:radial-gradient(500px circle at var(--gx,50%) var(--gy,50%),rgba(255,255,255,.14),transparent 40%);mix-blend-mode:overlay}
  .tilt.on .glare{opacity:1}
  .reveal{opacity:0;transform:translateY(26px) scale(.985)}
  .reveal.in{opacity:1;transform:none;transition:opacity .6s ease,transform .7s cubic-bezier(.16,1,.3,1)}
  .wipe{animation:wipeIn .9s cubic-bezier(.16,1,.3,1) both}
  @keyframes wipeIn{from{clip-path:inset(0 100% 0 0);transform:translateX(-14px);letter-spacing:6px}to{clip-path:inset(0 0 0 0)}}
  `;
  document.head.appendChild(css);

  /* ---------- 3D tilt with glare ---------- */
  // Not .fixture: those hold drag sliders, which need a flat card to map the pointer.
  const TILT = '.ft, .hero.card, .forecast-card, .metric, .slip-item, .badge-card';
  function tiltable(card){
    if(card.dataset.tiltReady || !fine) return;
    card.dataset.tiltReady = '1'; card.classList.add('tilt');
    const glare = document.createElement('span'); glare.className = 'glare'; card.appendChild(glare);
    card.addEventListener('pointermove', e => {
      if(reduced() || off()) return;
      const r = card.getBoundingClientRect(), x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
      const max = Math.max(2.5, 7 - r.width / 260);   // big cards tilt less
      card.classList.add('on');
      card.style.transform = `perspective(900px) rotateX(${(0.5 - y) * max}deg) rotateY(${(x - 0.5) * max}deg) translateZ(0)`;
      card.style.setProperty('--gx', x * 100 + '%'); card.style.setProperty('--gy', y * 100 + '%');
    });
    card.addEventListener('pointerleave', () => { card.classList.remove('on'); card.style.transform = '' });
  }

  /* ---------- Magnetic buttons ---------- */
  function magnetic(btn){
    if(btn.dataset.magReady || !fine) return;
    btn.dataset.magReady = '1';
    btn.addEventListener('pointermove', e => {
      if(reduced() || off()) return;
      const r = btn.getBoundingClientRect(), dx = e.clientX - (r.left + r.width / 2), dy = e.clientY - (r.top + r.height / 2);
      btn.style.transform = `translate(${dx * 0.12}px, ${dy * 0.22}px)`;
    });
    btn.addEventListener('pointerleave', () => { btn.style.transform = '' });
  }

  /* ---------- Scroll reveal ---------- */
  const io = 'IntersectionObserver' in window ? new IntersectionObserver(entries => {
    for(const en of entries) if(en.isIntersecting){ en.target.classList.add('in'); io.unobserve(en.target) }
  }, {rootMargin: '0px 0px -8% 0px'}) : null;
  function revealable(el){
    if(!io || el.dataset.revealReady || reduced() || off()) return;
    el.dataset.revealReady = '1';
    const r = el.getBoundingClientRect();
    if(r.top < innerHeight) return;            // already on screen: leave it alone
    el.classList.add('reveal'); io.observe(el);
  }

  /* ---------- Headlines sweep in (keeps gradient text intact) ---------- */
  function split(h){
    if(reduced() || off()) return;
    h.classList.remove('wipe'); void h.offsetWidth; h.classList.add('wipe');
  }

  /* ---------- Wire up, including content rendered later ---------- */
  function scan(root){
    root.querySelectorAll && root.querySelectorAll(TILT).forEach(tiltable);
    root.querySelectorAll && root.querySelectorAll('.primary, .cta, .big-btn').forEach(magnetic);
    root.querySelectorAll && root.querySelectorAll('.card, .fx, .ft').forEach(revealable);
  }
  function headlines(){ document.querySelectorAll('.view-head h1, .hero h1').forEach(h => { if(h.offsetParent) split(h) }) }
  function start(){
    scan(document); headlines();
    new MutationObserver(muts => {
      for(const m of muts) for(const n of m.addedNodes) if(n.nodeType === 1){ scan(n); if(n.matches && n.matches(TILT)) tiltable(n) }
    }).observe(document.body, {childList: true, subtree: true});
    addEventListener('hashchange', () => setTimeout(headlines, 30));
  }
  document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', start) : start();
})();
