(() => {
  let data=null,todayData=null,generation=0,editorId=null,editorRevision=null,pending=false;
  const days=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
  const $t=id=>document.getElementById(id);
  const dateText=value=>new Date(value+'T12:00:00Z').toLocaleDateString(undefined,{weekday:'long',day:'numeric',month:'short',year:'numeric',timeZone:'UTC'});
  function canSwitch(){return !busy&&$t('video-attendance-button').getAttribute('aria-pressed')!=='true';}
  function classes(){return academicData().classes;}
  function subjectOptions(selected='') {
    const rows=academicData().subjects.filter(row=>row.class_id===$t('timetable-edit-class').value);
    $t('timetable-edit-subject').innerHTML=rows.length?rows.map(row=>`<option value="${escapeHTML(row.id)}">${escapeHTML(row.name)}</option>`).join(''):'<option value="">Add a subject to this class first</option>';
    if(rows.some(row=>row.id===selected))$t('timetable-edit-subject').value=selected;
  }
  function stateClass(value){return {'Completed':'done','In progress':'progress','Upcoming':'upcoming','Needs attendance':'needed'}[value]||'needed';}
  function action(row,source) {
    const future=source.date>source.today;
    return `<button class="button ${row.status==='Completed'?'secondary':'primary'}" data-scheduled-start="${row.schedule.slot_id}" data-scheduled-date="${source.date}" ${(!row.available||(!row.lecture_id&&future))?'disabled':''}>${row.status==='Completed'?'View attendance ↗':row.lecture_id?'Resume attendance →':future?'Opens on class date':'Start attendance →'}</button>`;
  }
  function card(row,source,compact=false) {
    return `<article class="timetable-occurrence ${compact?'compact':''}"><div class="timetable-time"><strong>${escapeHTML(row.schedule.start_time)}</strong><span>to ${escapeHTML(row.schedule.end_time)}</span></div><div class="timetable-occurrence-copy"><span class="timetable-state ${stateClass(row.status)}">${row.status}</span><h3>${escapeHTML(row.title)}</h3><p>${escapeHTML(row.class_name)} · ${escapeHTML(row.subject_name)}</p><small>Late after ${row.schedule.late_after_minutes} min${row.summary?' · '+row.summary.present+' / '+row.summary.students+' present':''}</small>${!row.available?'<p class="timetable-warning">The class or subject is unavailable. Edit the weekly slot before starting.</p>':''}${row.changed?'<p class="timetable-warning">Saved session keeps its original timetable.</p>':''}</div>${action(row,source)}</article>`;
  }
  function stats(target,source,rows=source.occurrences) {
    const values=[['Classes',rows.length],['Completed',rows.filter(row=>row.status==='Completed').length],['In progress',rows.filter(row=>row.status==='In progress').length],['Needs attendance',rows.filter(row=>row.status==='Needs attendance').length]];
    $t(target).innerHTML=values.map(([label,value])=>`<div><strong>${value}</strong><span>${label}</span></div>`).join('');
  }
  function renderDay() {
    if(!data)return;
    const selected=$t('timetable-class-filter').value;
    const groups=new Map(classes().map(row=>[row.id,row.name]));
    for(const row of data.occurrences)groups.set(row.class_id,row.class_name);
    $t('timetable-class-filter').innerHTML='<option value="">All classes</option>'+[...groups].map(([id,name])=>`<option value="${escapeHTML(id)}">${escapeHTML(name)}</option>`).join('');
    if(groups.has(selected))$t('timetable-class-filter').value=selected;
    const filter=$t('timetable-class-filter').value,rows=data.occurrences.filter(row=>!filter||row.class_id===filter);
    $t('timetable-day-title').textContent=(data.date===data.today?'Today · ':'')+dateText(data.date);
    $t('timetable-zone').textContent=`All timetable times use ${data.timezone}. Finalizing attendance marks a session complete.`;
    stats('timetable-day-stats',data,rows);
    $t('timetable-day-list').innerHTML=rows.length?rows.map(row=>card(row,data)).join(''):'<div class="timetable-empty"><span aria-hidden="true">▧</span><h3>No classes scheduled for this day.</h3><p>Add a repeating slot or choose another day.</p><button class="button secondary" data-timetable-new>Add a timetable slot</button></div>';
    const entries=data.entries.filter(row=>!filter||row.class_id===filter).slice().sort((a,b)=>Math.min(...a.weekdays)-Math.min(...b.weekdays)||a.start_time.localeCompare(b.start_time));
    $t('timetable-week-list').innerHTML=entries.length?entries.map(entry=>`<article class="timetable-week-slot"><div><span class="timetable-state ${entry.active?'upcoming':'paused'}">${entry.active?'Active':'Paused'}</span><h3>${escapeHTML(entry.title||entry.subject_name)}</h3><p>${escapeHTML(entry.class_name)} · ${escapeHTML(entry.subject_name)}</p><small>${entry.weekdays.map(day=>days[day]).join(' · ')} · ${entry.start_time}–${entry.end_time} · Late after ${entry.late_after_minutes} min</small><small>From ${entry.starts_on}${entry.ends_on?' through '+entry.ends_on:''}</small>${!entry.available?'<p class="timetable-warning">Choose an available class and subject to use this slot.</p>':''}</div><button class="button secondary" data-timetable-edit="${entry.id}">Edit slot</button></article>`).join(''):'<div class="timetable-empty"><h3>Give your week a rhythm.</h3><p>Create classes and subjects, then add their usual days and times.</p><button class="text-button" data-timetable-classes>Manage classes & subjects ↗</button></div>';
  }
  function renderToday() {
    if(!todayData)return;
    $t('dashboard-today-date').textContent=`${dateText(todayData.date)} · ${todayData.timezone}`;
    stats('dashboard-today-stats',todayData);
    $t('dashboard-today-list').innerHTML=todayData.occurrences.length?todayData.occurrences.map(row=>card(row,todayData,true)).join(''):'<p class="timetable-empty-note">No classes scheduled today. Add your weekly slots in Timetable.</p>';
    const rows=todayData.occurrences.filter(row=>row.status!=='Completed').slice(0,2);
    $t('attendance-today-list').innerHTML=rows.length?rows.map(row=>card(row,todayData,true)).join(''):todayData.occurrences.length?'<p class="timetable-empty-note">Today’s scheduled attendance is complete. You can still start an unscheduled lecture below.</p>':'<p class="timetable-empty-note">Add your regular classes and start attendance with the right class and subject already selected.</p>';
  }
  async function load() {
    if(busy){pending=true;return;}
    const version=++generation,date=$t('timetable-date').value;
    try {
      const result=await api('/api/timetable'+(date?'?date='+encodeURIComponent(date):''));
      if(version!==generation)return;
      data=result;$t('timetable-date').value=result.date;$t('timetable-message').textContent='';
      if(result.date===result.today)todayData=result;
      else {
        const today=await api('/api/timetable');if(version!==generation)return;todayData=today;
      }
      renderDay();renderToday();window.updateTimetableControls();
    } catch(error) {
      if(version!==generation)return;
      $t('timetable-message').textContent=error.message;
      if(!todayData){$t('attendance-today-list').textContent='Timetable could not load. Open Timetable and choose Refresh to retry.';$t('dashboard-today-list').textContent=error.message;}
    }
  }
  window.refreshTimetable=()=>{pending=true;if(!busy){pending=false;void load();}};
  window.updateTimetableControls=()=>{
    const locked=!canSwitch();
    $t('attendance-today').hidden=Boolean(captureLecture);
    for(const id of ['timetable-new','timetable-save'])$t(id).disabled=locked;
    document.querySelectorAll('[data-scheduled-start],[data-timetable-edit],[data-timetable-new]').forEach(button=>{
      if(button.hasAttribute('data-scheduled-start')){
        const source=[data,todayData].find(value=>value?.date===button.dataset.scheduledDate);
        const row=source?.occurrences.find(row=>row.schedule.slot_id===button.dataset.scheduledStart);
        button.disabled=locked||!row?.available||(!row.lecture_id&&source.date>source.today);
      }else button.disabled=locked;
    });
    $t('timetable-form').querySelectorAll('input,select').forEach(input=>{input.disabled=busy;});
    if(pending&&!busy){pending=false;Promise.resolve().then(load);}
  };
  function edit(id=null) {
    if(!canSwitch())return;
    if(!data){toast('Wait for the timetable to load, then try again.',true);return;}
    const groups=classes().filter(group=>academicData().subjects.some(subject=>subject.class_id===group.id));
    if(!groups.length){toast('Create a class and its subjects first.');navigate('classes');return;}
    const entry=id?data.entries.find(row=>row.id===id):null;
    if(id&&!entry){toast('Refresh the timetable before editing this slot.',true);return;}
    editorId=id;editorRevision=data.revision;$t('timetable-form').reset();
    $t('timetable-editor-title').textContent=id?'Edit timetable slot':'Add timetable slot';
    $t('timetable-editor-zone').textContent=data.timezone;
    $t('timetable-edit-class').innerHTML=groups.map(group=>`<option value="${escapeHTML(group.id)}">${escapeHTML(group.name)}</option>`).join('');
    if(entry&&groups.some(group=>group.id===entry.class_id))$t('timetable-edit-class').value=entry.class_id;
    subjectOptions(entry?.subject_id);
    $t('timetable-edit-title').value=entry?.title||'';$t('timetable-edit-start').value=entry?.start_time||(window.getAppPreferences?.() || {}).default_start_time||'09:00';$t('timetable-edit-end').value=entry?.end_time||(window.getAppPreferences?.() || {}).default_end_time||'10:00';
    $t('timetable-edit-since').value=entry?.starts_on||data.date;$t('timetable-edit-until').value=entry?.ends_on||'';
    $t('timetable-edit-late').value=entry?.late_after_minutes??(window.getAppPreferences?.() || {}).default_late_after_minutes??10;$t('timetable-edit-active').checked=entry?.active??true;
    document.querySelectorAll('[name="timetable-weekday"]').forEach(input=>{input.checked=entry?entry.weekdays.includes(Number(input.value)):Number(input.value)===(new Date(data.date+'T12:00:00Z').getUTCDay()+6)%7;});
    $t('timetable-edit-message').textContent='';$t('timetable-edit-frozen-note').textContent=entry?'Edits apply to sessions not yet started. Saved sessions keep their original timetable.':'Starting a session saves its roster and schedule.';
    $t('timetable-dialog').showModal();$t('timetable-edit-class').focus();
  }
  async function start(slot,date) {
    if(!canSwitch())return;
    const source=[data,todayData].find(row=>row?.date===date);if(!source)return;
    busy=true;updateControls();
    try {
      const response=await api('/api/timetable/start',{slot_id:slot,date,revision:source.revision});
      const item=response.lecture;
      const changed=captureLecture?.id!==item.id;
      viewedLecture=item;selectedCaptureId=item.captures[0]?.id||null;
      if(item.state==='finalized') {if(captureLecture?.id===item.id)captureLecture=null;renderLecture();navigate('lectures');}
      else {
        captureLecture=item;selectedClassId=item.context.class_id;selectedSubjectId=item.context.subject_id;
        if(changed){photoGeneration++;selectedImage=null;$t('class-file').value='';result=null;$t('results-panel').hidden=true;}
        navigate('attendance');setSource('upload');renderAcademicControls();renderCaptureLecture();
      }
      await refreshAfterSave(response.resumed?'Scheduled lecture opened.':'Scheduled lecture started. Add your first capture.');
    }catch(error){toast(error.message,true);}
    finally{busy=false;updateControls();void load();}
  }
  $t('timetable-form').addEventListener('submit',async event=>{
    event.preventDefault();if(!canSwitch())return;
    const weekdays=[...document.querySelectorAll('[name="timetable-weekday"]:checked')].map(input=>Number(input.value));
    if(!weekdays.length){$t('timetable-edit-message').textContent='Choose at least one weekday.';return;}
    busy=true;updateControls();
    try {
      const payload={revision:editorRevision,...(editorId?{id:editorId}:{}),class_id:$t('timetable-edit-class').value,subject_id:$t('timetable-edit-subject').value,title:$t('timetable-edit-title').value,
        weekdays,start_time:$t('timetable-edit-start').value,end_time:$t('timetable-edit-end').value,starts_on:$t('timetable-edit-since').value,ends_on:$t('timetable-edit-until').value,
        late_after_minutes:Number($t('timetable-edit-late').value),active:$t('timetable-edit-active').checked};
      await api('/api/timetable',payload);$t('timetable-dialog').close();toast('Timetable slot saved.');
    }catch(error){$t('timetable-edit-message').textContent=error.message;}
    finally{busy=false;updateControls();void load();}
  });
  document.addEventListener('click',event=>{
    const button=event.target.closest('[data-scheduled-start],[data-timetable-edit],[data-timetable-new],[data-timetable-open],[data-timetable-classes]');if(!button||button.disabled)return;
    if(button.hasAttribute('data-scheduled-start'))void start(button.dataset.scheduledStart,button.dataset.scheduledDate);
    else if(button.hasAttribute('data-timetable-edit'))edit(button.dataset.timetableEdit);
    else if(button.hasAttribute('data-timetable-new'))edit();
    else if(button.hasAttribute('data-timetable-classes'))navigate('classes');
    else{$t('timetable-date').value=todayData?.today||'';navigate('timetable');void load();}
  });
  $t('timetable-new').addEventListener('click',()=>edit());
  $t('timetable-close').addEventListener('click',()=>$t('timetable-dialog').close());
  $t('timetable-edit-class').addEventListener('change',()=>subjectOptions());
  document.querySelector('[data-page="timetable"]').addEventListener('click',()=>void load());
  document.querySelector('[data-page="dashboard"]').addEventListener('click',()=>void load());
  $t('timetable-class-filter').addEventListener('change',()=>{renderDay();window.updateTimetableControls();});
  $t('timetable-date').addEventListener('change',()=>void load());
  $t('timetable-refresh').addEventListener('click',()=>void load());
  $t('timetable-today').addEventListener('click',()=>{$t('timetable-date').value=data?.today||'';void load();});
  for(const [id,delta] of [['timetable-prev',-1],['timetable-next',1]])$t(id).addEventListener('click',()=>{if(!data)return;const day=new Date(data.date+'T12:00:00Z');day.setUTCDate(day.getUTCDate()+delta);$t('timetable-date').value=day.toISOString().slice(0,10);void load();});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)window.refreshTimetable();});
  setInterval(()=>{if(!document.hidden&&['timetable','attendance','dashboard'].some(page=>!$t('page-'+page).hidden))window.refreshTimetable();},60000);
  void load();
})();
