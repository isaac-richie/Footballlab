/* Motion layer shared by every page: kickoff intro, 3D tilt cards, magnetic buttons,
   scroll reveal, sweeping headlines and a cursor ring. Everything is skipped
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
  .ko-intro{position:fixed;inset:0;z-index:1000;display:grid;place-items:center;background:#0a0d12;cursor:pointer}
  .ko-intro .lens{width:132px;height:132px;animation:koDrop .7s cubic-bezier(.2,1.4,.4,1) both}
  .ko-intro .lens img{width:100%;height:100%;animation:koSpin .9s cubic-bezier(.3,.8,.3,1) .15s both}
  .ko-intro .word{position:absolute;top:calc(50% + 86px);font:800 22px/1 'Barlow Condensed','Arial Narrow',sans-serif;letter-spacing:6px;color:#f4f7fb;text-transform:uppercase;opacity:0;animation:koWord .5s ease .45s both}
  .ko-intro .word b{color:#c2f25e}
  .ko-intro.out{animation:koOut .75s cubic-bezier(.7,0,.2,1) forwards}
  @keyframes koDrop{from{transform:translateY(-60vh) scale(.6);opacity:0}}
  @keyframes koSpin{from{transform:rotate(-540deg) scale(.4)}}
  @keyframes koWord{from{opacity:0;transform:translateY(10px);letter-spacing:16px}to{opacity:1}}
  @keyframes koOut{to{clip-path:circle(0 at 50% 50%);opacity:.6}}
  .ko-intro{clip-path:circle(150% at 50% 50%)}
  .tilt{transform-style:preserve-3d;will-change:transform;transition:transform .5s cubic-bezier(.2,.8,.2,1)}
  .tilt.on{transition:transform .08s linear}
  .tilt .glare{position:absolute;inset:0;border-radius:inherit;pointer-events:none;z-index:3;opacity:0;transition:opacity .3s;
    background:radial-gradient(500px circle at var(--gx,50%) var(--gy,50%),rgba(255,255,255,.14),transparent 40%);mix-blend-mode:overlay}
  .tilt.on .glare{opacity:1}
  .reveal{opacity:0;transform:translateY(26px) scale(.985)}
  .reveal.in{opacity:1;transform:none;transition:opacity .6s ease,transform .7s cubic-bezier(.16,1,.3,1)}
  .wipe{animation:wipeIn .9s cubic-bezier(.16,1,.3,1) both}
  @keyframes wipeIn{from{clip-path:inset(0 100% 0 0);transform:translateX(-14px);letter-spacing:6px}to{clip-path:inset(0 0 0 0)}}
  .cur-ring{position:fixed;left:0;top:0;width:34px;height:34px;margin:-17px 0 0 -17px;border:2px solid #c2f25e;border-radius:50%;pointer-events:none;z-index:999;
    transition:width .25s,height .25s,margin .25s,background .25s,border-color .25s,opacity .3s;mix-blend-mode:difference;opacity:0}
  .cur-ring.show{opacity:.85}
  .cur-ring.hot{width:58px;height:58px;margin:-29px 0 0 -29px;background:rgba(194,242,94,.12)}
  .cur-dot{position:fixed;left:0;top:0;width:6px;height:6px;margin:-3px 0 0 -3px;border-radius:50%;background:#c2f25e;pointer-events:none;z-index:999;opacity:0;transition:opacity .3s}
  .cur-dot.show{opacity:1}`;
  document.head.appendChild(css);

  /* ---------- Kickoff intro: once per visit ---------- */
  function intro(){
    let seen = false; try{ seen = sessionStorage.getItem('ko') === '1'; sessionStorage.setItem('ko', '1') }catch{}
    if(seen || reduced() || off()) return;
    const el = document.createElement('div');
    el.className = 'ko-intro'; el.setAttribute('aria-hidden', 'true');
    el.innerHTML = `<div class="lens"><img src="${logoSrc}" alt=""></div><div class="word">Football <b>Lab</b></div>`;
    document.body.appendChild(el);
    const leave = () => { if(el.classList.contains('out')) return; el.classList.add('out'); setTimeout(() => el.remove(), 800) };
    el.addEventListener('click', leave);
    setTimeout(leave, 1500);
  }

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

  /* ---------- Cursor ring ---------- */
  function cursor(){
    if(!fine) return;
    const ring = document.createElement('div'), dot = document.createElement('div');
    ring.className = 'cur-ring'; dot.className = 'cur-dot';
    document.body.append(ring, dot);
    let x = 0, y = 0, rx = 0, ry = 0;
    addEventListener('pointermove', e => {
      x = e.clientX; y = e.clientY;
      const show = !reduced() && !off() && !e.target.closest('canvas');   // games need a precise cursor
      ring.classList.toggle('show', show); dot.classList.toggle('show', show);
      ring.classList.toggle('hot', !!e.target.closest('a,button,select,input,summary,[role=slider],.fx,.ft'));
      dot.style.transform = `translate(${x}px,${y}px)`;
    }, {passive: true});
    document.addEventListener('pointerleave', () => { ring.classList.remove('show'); dot.classList.remove('show') });
    (function loop(){ rx += (x - rx) * 0.2; ry += (y - ry) * 0.2; ring.style.transform = `translate(${rx}px,${ry}px)`; requestAnimationFrame(loop) })();
  }

  /* ---------- Wire up, including content rendered later ---------- */
  function scan(root){
    root.querySelectorAll && root.querySelectorAll(TILT).forEach(tiltable);
    root.querySelectorAll && root.querySelectorAll('.primary, .cta, .big-btn').forEach(magnetic);
    root.querySelectorAll && root.querySelectorAll('.card, .fx, .ft').forEach(revealable);
  }
  function headlines(){ document.querySelectorAll('.view-head h1, .hero h1').forEach(h => { if(h.offsetParent) split(h) }) }
  function start(){
    intro(); cursor(); scan(document); headlines();
    new MutationObserver(muts => {
      for(const m of muts) for(const n of m.addedNodes) if(n.nodeType === 1){ scan(n); if(n.matches && n.matches(TILT)) tiltable(n) }
    }).observe(document.body, {childList: true, subtree: true});
    addEventListener('hashchange', () => setTimeout(headlines, 30));
  }
  document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', start) : start();
})();
