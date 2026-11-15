(() => {
  const dialog = document.getElementById('chess-dialog');
  const frame = document.getElementById('chess-frame');
  const trigger = document.getElementById('chess-trigger');
  let sequence = '';
  function open() {
    if (document.querySelector('dialog[open]')) return;
    // Turning off camera tracks also stops any live recognition loop.
    document.getElementById('stop-camera').click();
    if (!frame.getAttribute('src')) frame.src = '/static/chess.html?v=2';
    dialog.showModal();
  }
  trigger.addEventListener('click', open);
  document.addEventListener('keydown', event => {
    if (event.ctrlKey || event.metaKey || event.altKey || event.target.closest('input,textarea,select,[contenteditable],dialog')) return;
    if (event.key.length !== 1) { sequence=''; return; }
    sequence = (sequence + event.key.toLowerCase()).slice(-5);
    if (sequence === 'chess') { sequence=''; open(); }
  });
  document.getElementById('chess-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => trigger.focus());
})();
