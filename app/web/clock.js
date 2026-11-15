(() => {
  const clock = document.getElementById('workspace-clock');
  const date = document.getElementById('workspace-date');
  const timeFormat = new Intl.DateTimeFormat(undefined, {
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  });
  const dateFormat = new Intl.DateTimeFormat(undefined, {
    weekday: 'short', month: 'short', day: 'numeric',
  });
  const timeZone = timeFormat.resolvedOptions().timeZone;
  function tick() {
    if (document.hidden) return;
    const now = new Date();
    clock.textContent = timeFormat.format(now);
    clock.dateTime = now.toISOString();
    clock.title = `Local time · ${timeZone}`;
    date.textContent = dateFormat.format(now);
  }
  tick();
  setInterval(tick, 1000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) tick(); });
})();
