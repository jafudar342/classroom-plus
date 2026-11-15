// Apply the saved appearance before the stylesheet paints.
(() => {
  'use strict';
  const key = 'classroom-attendance-theme';
  const themes = ['light','dark','pop','oled'];
  const names = {light:'Light',dark:'Dark',pop:'Pop',oled:'OLED'};
  const colors = {light:'#edf0fb',dark:'#11192d',pop:'#171125',oled:'#000000'};
  const media = window.matchMedia?.('(prefers-color-scheme: dark)');
  let preference = null;
  try { preference = localStorage.getItem(key); } catch { /* Storage may be blocked. */ }
  if (!themes.includes(preference)) preference = null;
  const icons = {
    oled:'<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3" fill="currentColor" stroke="none"/></svg>',
    light:'<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" stroke-linecap="round"/></svg>',
    dark:'<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M20.3 14.3A8.7 8.7 0 0 1 9.7 3.7a8.7 8.7 0 1 0 10.6 10.6Z" stroke-linejoin="round"/></svg>',
    pop:'<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="m10 3 2.2 6.8L19 12l-6.8 2.2L10 21l-2.2-6.8L1 12l6.8-2.2L10 3Z" stroke-linejoin="round"/><path d="m20 2 .8 2.2L23 5l-2.2.8L20 8l-.8-2.2L17 5l2.2-.8L20 2Z"/></svg>'
  };
  function apply() {
    const theme = preference || (media?.matches ? 'dark' : 'light');
    document.documentElement.dataset.theme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content',colors[theme]);
    const button = document.getElementById('theme-toggle');
    if (button) {
      button.innerHTML = `${icons[theme]}<span>${names[theme]}</span><span class="theme-chevron" aria-hidden="true">⌄</span>`;
      button.setAttribute('aria-label',`Choose appearance, current theme: ${names[theme]}`);
      button.setAttribute('title',`Appearance: ${names[theme]}`);
    }
    document.querySelectorAll('[data-theme-choice]').forEach(option=>option.setAttribute('aria-pressed',String(option.dataset.themeChoice===theme)));
    window.dispatchEvent?.(new Event('classroom-theme-change'));
    return theme;
  }
  function close(restoreFocus=false) {
    const options = document.getElementById('theme-options');
    if (options) options.hidden = true;
    const button = document.getElementById('theme-toggle');
    button?.setAttribute('aria-expanded','false');
    if (restoreFocus) button?.focus();
  }
  function choose(theme,restoreFocus=true) {
    if (!themes.includes(theme)) return;
    preference = theme;
    try { localStorage.setItem(key,theme); } catch { /* Keep this tab usable. */ }
    apply(); close(restoreFocus);
  }
  window.setClassroomTheme=theme=>choose(theme,false);
  apply();
  media?.addEventListener?.('change',()=>{if(!preference)apply();});
  window.addEventListener('storage',event=>{
    if (event.key!==key && event.key!==null) return;
    preference=themes.includes(event.newValue) ? event.newValue : null;
    apply();
  });
  document.addEventListener('DOMContentLoaded',()=>{
    apply();
    document.getElementById('theme-toggle')?.addEventListener('click',()=>{
      const options=document.getElementById('theme-options');if(!options)return;
      options.hidden=!options.hidden;
      document.getElementById('theme-toggle').setAttribute('aria-expanded',String(!options.hidden));
      if (!options.hidden) document.querySelector(`[data-theme-choice="${document.documentElement.dataset.theme}"]`)?.focus();
    });
    document.querySelectorAll('[data-theme-choice]').forEach(option=>option.addEventListener('click',()=>choose(option.dataset.themeChoice)));
    document.addEventListener('click',event=>{if(!document.getElementById('theme-switcher')?.contains(event.target))close();});
    document.addEventListener('keydown',event=>{
      const options=document.getElementById('theme-options');
      if(event.key==='Escape' && options && !options.hidden){close(true);event.preventDefault();}
    });
    document.getElementById('theme-switcher')?.addEventListener('focusout',event=>{
      if(event.relatedTarget && !document.getElementById('theme-switcher').contains(event.relatedTarget))close();
    });
  });
})();
