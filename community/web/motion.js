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
  /* Welcome: the fair line draws, the mark closes round it, the name rises, then the screen shuts onto the line */
  .fl-intro{position:fixed;inset:0;z-index:1000;cursor:pointer;--lime:#c2f25e;--ink:#f4f7fb}
  .fl-stage{position:absolute;inset:0;overflow:hidden;background:radial-gradient(120% 80% at 50% 50%,#0f141b 0%,#07090c 70%);
    clip-path:inset(0 0 0 0);display:grid;place-items:center}
  .fl-stage::after{content:'';position:absolute;inset:0;pointer-events:none;opacity:.07;mix-blend-mode:overlay;
    background:repeating-radial-gradient(circle at 30% 40%,#fff 0 1px,transparent 1px 3px);animation:flGrain .4s steps(2) infinite}
  .fl-beam{position:absolute;top:-30vh;width:60vmax;height:140vh;opacity:0;pointer-events:none;filter:blur(18px);
    background:conic-gradient(from 180deg at 50% 0%,transparent 0deg,rgba(220,240,255,.16) 8deg,transparent 18deg)}
  .fl-beam.l{left:-22vmax;transform-origin:50% 0;animation:flBeamL 1.6s cubic-bezier(.3,.7,.2,1) .35s both}
  .fl-beam.r{right:-22vmax;transform-origin:50% 0;animation:flBeamR 1.6s cubic-bezier(.3,.7,.2,1) .45s both}
  .fl-core{position:relative;display:grid;justify-items:center;gap:22px;transform:translateY(-8px)}
  .fl-mark{width:112px;height:112px;overflow:visible;filter:drop-shadow(0 0 14px rgba(194,242,94,.28))}
  .fl-mark .ring{fill:none;stroke:var(--ink);stroke-width:1.6;stroke-dasharray:0 60;transform:rotate(-180deg);transform-origin:12px 12px;
    animation:flRing .75s cubic-bezier(.65,0,.35,1) .55s forwards}
  .fl-mark .fill{fill:var(--lime);clip-path:inset(100% 0 0 0);animation:flFill .5s cubic-bezier(.3,.8,.3,1) 1.05s forwards}
  .fl-word{display:flex;font:800 clamp(52px,15vw,96px)/.9 'Barlow Condensed','Arial Narrow',sans-serif;letter-spacing:2px;color:var(--ink);text-transform:uppercase;
    clip-path:inset(-20% -10% -20% -10%)}
  .fl-word span{display:inline-block;opacity:0;transform:translateY(60%);filter:blur(10px);animation:flRise .7s cubic-bezier(.16,1,.3,1) both;animation-delay:calc(1.2s + var(--i) * 55ms)}
  .fl-word span.l{color:var(--lime);text-shadow:0 0 28px rgba(194,242,94,.35)}
  .fl-tag{font:600 13px/1 Inter,system-ui,sans-serif;letter-spacing:5px;text-transform:uppercase;color:#8a96a8;opacity:0;animation:flTag .9s ease 1.75s both}
  .fl-line{position:absolute;left:0;right:0;top:50%;height:2px;margin-top:-1px;pointer-events:none;
    background:linear-gradient(90deg,transparent,var(--lime) 18%,var(--lime) 82%,transparent);box-shadow:0 0 18px 2px rgba(194,242,94,.55),0 0 60px 6px rgba(194,242,94,.18);
    transform:scaleX(0);animation:flLine .8s cubic-bezier(.65,0,.35,1) .1s forwards}
  .fl-intro.out .fl-stage{animation:flShut .62s cubic-bezier(.7,0,.25,1) forwards}
  .fl-intro.out .fl-line{animation:flFlash .9s ease .45s forwards;transform:scaleX(1)}
  @keyframes flLine{to{transform:scaleX(1)}}
  @keyframes flRing{to{stroke-dasharray:57.5 60}}
  @keyframes flFill{to{clip-path:inset(50% 0 0 0)}}
  @keyframes flRise{to{opacity:1;transform:none;filter:blur(0)}}
  @keyframes flTag{from{opacity:0;letter-spacing:12px}to{opacity:1}}
  @keyframes flBeamL{0%{opacity:0;transform:rotate(-38deg)}40%{opacity:1}100%{opacity:.55;transform:rotate(-14deg)}}
  @keyframes flBeamR{0%{opacity:0;transform:rotate(38deg)}40%{opacity:1}100%{opacity:.55;transform:rotate(14deg)}}
  @keyframes flShut{to{clip-path:inset(var(--y,50%) 0 calc(100% - var(--y,50%)) 0)}}
  @keyframes flFlash{0%{opacity:1;filter:brightness(1.8)}100%{opacity:0;transform:scaleX(1.15);filter:brightness(1)}}
  @keyframes flGrain{50%{transform:translate(-1%,1%)}}
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

  /* ---------- Welcome: once per visit, a tap skips it ---------- */
  function intro(){
    let seen = false; try{ seen = sessionStorage.getItem('ko') === '1'; sessionStorage.setItem('ko', '1') }catch{}
    if(seen || reduced() || off()) return;
    const el = document.createElement('div');
    el.className = 'fl-intro'; el.setAttribute('aria-hidden', 'true');
    const letters = [...'FAIRLINE'].map((c, i) => `<span${i > 3 ? ' class="l"' : ''} style="--i:${i}">${c}</span>`).join('');
    el.innerHTML = `<div class="fl-stage"><i class="fl-beam l"></i><i class="fl-beam r"></i>
        <div class="fl-core">
          <svg class="fl-mark" viewBox="0 0 24 24"><path class="fill" d="M3 12a9 9 0 0 0 18 0z"/><circle class="ring" cx="12" cy="12" r="9" pathLength="57"/></svg>
          <div class="fl-word">${letters}</div>
          <div class="fl-tag">The fair price on every game</div>
        </div></div><i class="fl-line"></i>`;
    document.body.appendChild(el);
    // the line runs through the middle of the mark
    const place = () => { const m = el.querySelector('.fl-mark').getBoundingClientRect(); const y = m.top + m.height / 2; el.querySelector('.fl-line').style.top = y + 'px'; el.style.setProperty('--y', y + 'px') };
    place();
    const leave = () => { if(el.classList.contains('out')) return; place(); el.classList.add('out'); setTimeout(() => el.remove(), 1400) };
    el.addEventListener('click', leave);
    setTimeout(leave, 2700);
  }
  // replay on demand (for demos): fairlineIntro()
  window.fairlineIntro = () => { try{ sessionStorage.removeItem('ko') }catch{} intro() };

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
