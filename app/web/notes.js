(() => {
  const el = id => document.getElementById(id);
  let data = null, editing = null, pending = false;
  const layer = document.createElement('div');
  layer.setAttribute('aria-label', 'Sticky notes');
  document.body.append(layer);
  const status = message => { el('notes-status').textContent = message; };
  function button(label, action) {
    const b = document.createElement('button'); b.type = 'button'; b.className = 'button secondary'; b.textContent = label; b.onclick = action; return b;
  }
  function position(node, note) {
    node.style.left = `${note.x * Math.max(0, innerWidth - node.offsetWidth - 12)}px`;
    node.style.top = `${note.y * Math.max(0, innerHeight - node.offsetHeight - 12)}px`;
  }
  async function mutate(payload) {
    if (pending || !data) return;
    pending = true; el('notes-save').disabled = true;
    try { data = await api('/api/notes', {...payload, revision: data.revision}); render(); status('Saved.'); return true; }
    catch (error) { status(error.message); toast(error.message, true); return false; }
    finally { pending = false; el('notes-save').disabled = false; }
  }
  function sticky(note) {
    const node = document.createElement('aside'); node.className = 'sticky-note'; node.dataset.id = note.id;
    const handle = document.createElement('div'); handle.className = 'sticky-handle'; handle.tabIndex = 0; handle.setAttribute('aria-label', 'Move sticky note. Use arrow keys to move.');
    const title = document.createElement('span'); title.className = 'sticky-hint'; title.textContent = 'STICKY NOTE · DRAG';
    const close = button('×', () => mutate({action:'sticky', id:note.id, sticky:false})); close.setAttribute('aria-label', 'Hide sticky note'); close.title = 'Hide from screen; keep in Notes';
    handle.append(title, close);
    const copy = document.createElement('p'); copy.className = 'note-copy'; copy.textContent = note.text; node.append(handle, copy); layer.append(node); position(node,note);
    let drag = null;
    handle.onpointerdown = event => {
      if (event.target.closest('button') || pending || event.button !== 0) return;
      drag = {x:event.clientX, y:event.clientY, left:node.offsetLeft, top:node.offsetTop}; handle.setPointerCapture(event.pointerId); event.preventDefault();
    };
    handle.onpointermove = event => {
      if (!drag) return;
      node.style.left = `${Math.max(0,Math.min(innerWidth-node.offsetWidth-12,drag.left+event.clientX-drag.x))}px`;
      node.style.top = `${Math.max(0,Math.min(innerHeight-node.offsetHeight-12,drag.top+event.clientY-drag.y))}px`;
    };
    const savePosition = () => mutate({action:'move',id:note.id,x:Math.min(1,node.offsetLeft/Math.max(1,innerWidth-node.offsetWidth-12)),y:Math.min(1,node.offsetTop/Math.max(1,innerHeight-node.offsetHeight-12))});
    handle.onpointerup = () => { if (drag) { drag=null; savePosition(); } };
    handle.onpointercancel = () => { drag=null; position(node,note); };
    handle.onkeydown = event => {
      if (event.target !== handle || !['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key) || pending) return;
      event.preventDefault(); const key=event.key;
      node.style.left = `${Math.max(0,Math.min(innerWidth-node.offsetWidth-12,node.offsetLeft+(key==='ArrowRight'?20:key==='ArrowLeft'?-20:0)))}px`;
      node.style.top = `${Math.max(0,Math.min(innerHeight-node.offsetHeight-12,node.offsetTop+(key==='ArrowDown'?20:key==='ArrowUp'?-20:0)))}px`; savePosition();
    };
  }
  function render() {
    el('notes-cards').replaceChildren(); layer.replaceChildren();
    if (!data.notes.length) { const p=document.createElement('p'); p.className='notes-empty'; p.textContent='Your ideas belong here. Write your first note above.'; el('notes-cards').append(p); }
    for (const note of data.notes) {
      const card=document.createElement('article'); card.className='panel note-card';
      const copy=document.createElement('p'); copy.className='note-copy'; copy.textContent=note.text;
      const actions=document.createElement('div'); actions.className='note-actions';
      actions.append(button('Edit',()=>{editing=note.id;el('notes-text').value=note.text;el('notes-cancel').hidden=false;el('notes-text').focus();}),button(note.sticky?'Hide sticky':'Show as sticky',()=>mutate({action:'sticky',id:note.id,sticky:!note.sticky})),button('Delete',async()=>{if(confirm('Delete this saved note?')) {if(await mutate({action:'delete',id:note.id}) && editing===note.id) reset();}}));
      card.append(copy,actions); el('notes-cards').append(card); if(note.sticky)sticky(note);
    }
  }
  function reset(){editing=null;el('notes-text').value='';el('notes-cancel').hidden=true;}
  async function load(){if(pending)return;try{data=await api('/api/notes');render();status('');}catch(error){status(error.message);if(error.status===409)setTimeout(load,1500);}}
  el('notes-form').onsubmit=async event=>{event.preventDefault();if(await mutate({action:editing?'edit':'create',id:editing,text:el('notes-text').value}))reset();};
  el('notes-cancel').onclick=reset; el('notes-reload').onclick=load;
  document.querySelector('[data-page="notes"]').addEventListener('click',()=>{el('breadcrumb').textContent='Notes';load();});
  window.addEventListener('resize',()=>{for(const node of layer.children){const note=data?.notes.find(n=>n.id===node.dataset.id);if(note)position(node,note);}});
  load();
})();
