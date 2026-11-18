(() => {
  const el=id=>document.getElementById(id);
  let data=null,editing=null,pending=false,loading=false;
  const announced=new Set();
  const alert=document.createElement('aside');alert.className='reminder-alert';alert.hidden=true;alert.setAttribute('role','status');document.body.append(alert);
  el('reminder-zone').textContent=`Times use your current time zone: ${Intl.DateTimeFormat().resolvedOptions().timeZone}.`;
  const status=text=>el('reminders-status').textContent=text;
  function button(text,fn){const b=document.createElement('button');b.type='button';b.className='button secondary';b.textContent=text;b.onclick=fn;return b;}
  function reset(){editing=null;el('reminders-form').reset();el('reminder-cancel').hidden=true;el('reminder-save').textContent='Add reminder';}
  function dueItems(){return(data?.reminders||[]).filter(r=>!r.completed && Date.parse(r.due)<=Date.now());}
  function check(){
    const due=dueItems();el('reminders-count').textContent=due.length;
    const fresh=due.filter(r=>!announced.has(r.id+ r.due));
    if(fresh.length){for(const r of fresh)announced.add(r.id+r.due);alert.replaceChildren();const text=document.createElement('p');text.textContent=fresh.length===1?`Reminder: ${fresh[0].text}`:`${fresh.length} reminders are due. Open Reminders to review them.`;alert.append(text,button('Dismiss',()=>{alert.hidden=true;}));alert.hidden=false;}
    if(!due.length)alert.hidden=true;
  }
  function render(){
    const list=el('reminders-list');list.replaceChildren();
    const items=[...(data?.reminders||[])].sort((a,b)=>Number(a.completed)-Number(b.completed)||Date.parse(a.due)-Date.parse(b.due));
    if(!items.length){const p=document.createElement('p');p.textContent='No reminders yet. Add your first one above.';list.append(p);}
    for(const r of items){
      const overdue=!r.completed && Date.parse(r.due)<=Date.now();const card=document.createElement('article');card.className=`panel reminder-card ${r.completed?'completed':overdue?'overdue':''}`;
      const text=document.createElement('h3');text.textContent=r.text;const date=document.createElement('time');date.dateTime=r.due;date.textContent=`${r.completed?'Completed':overdue?'Due':'Upcoming'} · ${new Date(r.due).toLocaleString()}`;
      const actions=document.createElement('div');actions.className='reminder-actions';actions.append(button(r.completed?'Reopen':'Mark complete',()=>save({action:'complete',id:r.id,completed:!r.completed})),button('Edit',()=>{editing=r.id;el('reminder-text').value=r.text;const d=new Date(r.due);el('reminder-due').value=`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}T${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;el('reminder-cancel').hidden=false;el('reminder-save').textContent='Save changes';el('reminder-text').focus();}),button('Delete',async()=>{if(confirm('Delete this reminder?') && await save({action:'delete',id:r.id}) && editing===r.id)reset();}));card.append(text,date,actions);list.append(card);
    }check();
  }
  async function load(){if(pending||loading)return;loading=true;try{data=await api('/api/reminders');render();status('');}catch(error){status(error.message);}finally{loading=false;}}
  async function save(payload){if(pending||loading||!data)return false;pending=true;el('reminder-save').disabled=true;try{data=await api('/api/reminders',{...payload,revision:data.revision});render();status('Saved.');return true;}catch(error){status(error.message);toast(error.message,true);return false;}finally{pending=false;el('reminder-save').disabled=false;}}
  el('reminders-form').onsubmit=async event=>{event.preventDefault();const date=new Date(el('reminder-due').value);if(!Number.isFinite(date.getTime())){status('Choose a valid date and time.');return;}if(await save({action:editing?'edit':'create',id:editing,text:el('reminder-text').value,due:date.toISOString()}))reset();};
  el('reminder-cancel').onclick=reset;el('reminders-reload').onclick=load;
  document.querySelector('[data-page="reminders"]').addEventListener('click',()=>{el('breadcrumb').textContent='Reminders';load();});
  setInterval(()=>{if(!document.hidden)load();},30000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)load();});load();
})();
