// Video-only overlay: a visible cursor, click ripples and highlight boxes. Injected by record.py.
(() => {
  if (window.__demo || location.protocol === 'file:') return;
  const css = `
#__cur{position:fixed;left:0;top:0;z-index:2147483647;pointer-events:none;
  transition:transform .45s cubic-bezier(.45,0,.2,1);will-change:transform}
#__cur svg{width:26px;height:26px;filter:drop-shadow(0 2px 5px rgba(0,0,0,.7))}
.__ripple{position:fixed;z-index:2147483646;pointer-events:none;width:48px;height:48px;margin:-24px 0 0 -24px;
  border-radius:50%;border:3px solid #22d3ee;animation:__rip .55s ease-out forwards}
@keyframes __rip{from{transform:scale(.3);opacity:1}to{transform:scale(1.5);opacity:0}}
.__spot{position:fixed;z-index:2147483645;pointer-events:none;border:3px solid var(--spot,#fbbf24);border-radius:12px;
  box-shadow:0 0 0 6px color-mix(in srgb,var(--spot,#fbbf24) 22%,transparent),0 0 34px color-mix(in srgb,var(--spot,#fbbf24) 60%,transparent);
  animation:__spotin .35s cubic-bezier(.2,.8,.2,1);transition:opacity .3s}
@keyframes __spotin{from{opacity:0;transform:scale(1.08)}to{opacity:1;transform:none}}`;
  const pos = {x: 900, y: 500};
  function mount() {
    if (document.getElementById('__cur')) return;
    const style = document.createElement('style');
    style.textContent = css;
    document.head.append(style);
    const cur = document.createElement('div');
    cur.id = '__cur';
    cur.innerHTML = '<svg viewBox="0 0 24 24"><path d="M4 2l16 10.5-7.2 1.4 4.3 7.6-3 1.6-4.2-7.7L4 20z" fill="#fff" stroke="#0b1a24" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    cur.style.transform = `translate(${pos.x - 4}px,${pos.y - 2}px)`;
    document.body.append(cur);
  }
  window.__demo = {
    place(x, y) { pos.x = x; pos.y = y; mount(); const c = document.getElementById('__cur');
      c.style.transition = 'none'; c.style.transform = `translate(${x - 4}px,${y - 2}px)`; c.offsetHeight; c.style.transition = ''; },
    move(x, y, ms = 450) { mount(); pos.x = x; pos.y = y; const c = document.getElementById('__cur');
      c.style.transitionDuration = ms + 'ms'; c.style.transform = `translate(${x - 4}px,${y - 2}px)`; },
    ripple() { const r = document.createElement('div'); r.className = '__ripple';
      r.style.left = pos.x + 'px'; r.style.top = pos.y + 'px'; document.body.append(r); setTimeout(() => r.remove(), 700); },
    spot(el, color, pad = 8) { const b = el.getBoundingClientRect(); const s = document.createElement('div');
      s.className = '__spot'; if (color) s.style.setProperty('--spot', color);
      Object.assign(s.style, {left: b.left - pad + 'px', top: b.top - pad + 'px', width: b.width + 2 * pad + 'px', height: b.height + 2 * pad + 'px'});
      document.body.append(s); },
    clear() { document.querySelectorAll('.__spot').forEach(s => { s.style.opacity = 0; setTimeout(() => s.remove(), 300); }); },
    pos() { return pos; },
  };
  if (document.body) mount(); else document.addEventListener('DOMContentLoaded', mount);
})();
