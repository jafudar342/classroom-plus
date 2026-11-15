(() => {
  const el = id => document.getElementById(id);
  let catalog = {photos:[],runs:[]};
  const selected = new Set();
  let imageData = null;
  let editing = null;
  let labels = [];
  let dragStart = null;
  let dragEnd = null;
  let experiment = null;
  let scoringVersion = 0;
  let scoringTimer;
  let fileVersion=0;
  const message = (id,text) => { el(id).textContent=text; };
  const percent = value => value === null ? '—' : `${value.toFixed(1)}%`;
  const outcomeNames = {correct:'Correct identity',wrong:'Wrong identity',missed:'Missed student',unknown_rejected:'Unknown rejected',unknown_false_accept:'Unknown falsely identified'};
  function setWorking(value) {
    busy=value;
    updateControls();
    el('page-evaluation').querySelectorAll('button,input,select').forEach(node => {node.disabled=value;});
    el('eval-photo-title').disabled=Boolean(editing)||value;
    el('eval-photo-split').disabled=Boolean(editing)||value;
    el('eval-independent').disabled=Boolean(editing)||value;
  }
  async function refreshCatalog() {
    catalog=await api('/api/evaluation');
    renderCatalog();
  }
  function renderCatalog() {
    const split=el('eval-split-filter').value;
    el('eval-photo-list').innerHTML=catalog.photos.filter(photo=>photo.split===split).map(photo=>`<article class="eval-photo-card"><img src="/api/evaluation/photos/${photo.id}/image" alt="${escapeHTML(photo.title)}" loading="lazy"><div><label><input type="checkbox" data-eval-photo="${photo.id}" ${selected.has(photo.id)?'checked':''}> ${escapeHTML(photo.title)}</label><p>${photo.labels.length} ${photo.labels.length===1?'person':'people'} labeled · revision ${photo.revision}</p><button class="text-button" data-eval-edit="${photo.id}">View / edit labels</button></div></article>`).join('') || '<p class="empty-state">Add separate photos and label every person to begin.</p>';
    const previous=el('eval-run-history').value;
    el('eval-run-history').innerHTML='<option value="">Choose an experiment</option>'+catalog.runs.map(run=>`<option value="${run.id}">${escapeHTML(formatTime(run.created_utc))} · ${run.photo_ids.length} photo(s)</option>`).join('');
    el('eval-run-history').value=previous;
  }
  function imageSize() { return {w:el('eval-source').naturalWidth,h:el('eval-source').naturalHeight}; }
  function renderBoxes() {
    const size=imageSize();
    if (!size.w) return;
    el('eval-boxes').setAttribute('viewBox',`0 0 ${size.w} ${size.h}`);
    let markup=labels.map((box,index)=>`<rect x="${box.x}" y="${box.y}" width="${box.w}" height="${box.h}" class="eval-truth-box"/><text x="${box.x+3}" y="${box.y+15}">${index+1}</text>`).join('');
    if (dragStart&&dragEnd) markup+=`<rect x="${Math.min(dragStart.x,dragEnd.x)}" y="${Math.min(dragStart.y,dragEnd.y)}" width="${Math.abs(dragStart.x-dragEnd.x)}" height="${Math.abs(dragStart.y-dragEnd.y)}" class="eval-draft-box"/>`;
    el('eval-boxes').innerHTML=markup;
  }
  function renderLabels() {
    el('eval-label-list').innerHTML=labels.map((box,index)=>{
      const available=(state?.students||[]).some(student=>student.roll_number===box.roll_number);
      const missing=box.source_index!==undefined ? `<option value="saved:${box.source_index}">${escapeHTML(box.name)} · Roll ${escapeHTML(box.roll_number==='unknown'?'—':box.roll_number)} (saved label)</option>` : box.roll_number&&box.roll_number!=='unknown'&&!available ? `<option value="${escapeHTML(box.roll_number)}">Roll ${escapeHTML(box.roll_number)} unavailable · choose a current label</option>`:'';
      return `<div class="eval-label-row"><span>Box ${index+1}<small>${box.x}, ${box.y} · ${box.w}×${box.h}px</small></span><select data-eval-label="${index}" aria-label="Expected identity for box ${index+1}"><option value="">Choose expected identity</option><option value="unknown">Unregistered person</option>${missing}${(state?.students||[]).map(student=>`<option value="${escapeHTML(student.roll_number)}">${escapeHTML(student.roll_number)} · ${escapeHTML(student.name)}</option>`).join('')}</select><button data-eval-remove="${index}" class="text-button">Remove box ${index+1}</button></div>`;
    }).join('');
    el('eval-label-list').querySelectorAll('[data-eval-label]').forEach(select=>{const row=labels[Number(select.dataset.evalLabel)];select.value=row.source_index!==undefined ? 'saved:'+row.source_index : row.roll_number;});
    renderBoxes();
  }
  function addBox(box) {
    const size=imageSize();
    if (!size.w || Object.values(box).some(value=>!Number.isInteger(value)) || box.x<0 || box.y<0 || box.w<8 || box.h<8 || box.x+box.w>size.w || box.y+box.h>size.h) {
      message('eval-draw-message','Draw or enter a box at least 8×8 pixels inside the photo.');return;
    }
    if (labels.some(other=>Math.min(box.x+box.w,other.x+other.w)>Math.max(box.x,other.x) && Math.min(box.y+box.h,other.y+other.h)>Math.max(box.y,other.y))) {
      message('eval-draw-message','Boxes must not overlap. Remove or redraw the existing box.');return;
    }
    labels.push({...box,roll_number:''});
    el('eval-complete').checked=false;
    message('eval-draw-message',`Box ${labels.length} added. Choose its expected identity.`);
    renderLabels();
  }
  function point(event) {
    const rect=el('eval-boxes').getBoundingClientRect(),size=imageSize();
    return {x:Math.round(Math.max(0,Math.min(size.w,(event.clientX-rect.left)*size.w/rect.width))),y:Math.round(Math.max(0,Math.min(size.h,(event.clientY-rect.top)*size.h/rect.height)))};
  }
  function showEditor(record,src) {
    editing=record;
    labels=record ? record.labels.map((row,index)=>({...row,source_index:index,roll_number:row.identity===null?'unknown':row.roll_number})) : [];
    el('eval-editor').hidden=false;
    el('eval-editor-title').textContent=record?'Edit ground-truth labels':'Label a test photo';
    el('eval-photo-title').value=record?.title || '';
    el('eval-photo-title').disabled=Boolean(record);
    el('eval-photo-split').value=record?.split || el('eval-split-filter').value;
    el('eval-photo-split').disabled=Boolean(record);
    el('eval-independent').checked=Boolean(record);
    el('eval-independent').disabled=Boolean(record);
    el('eval-complete').checked=false;
    el('eval-source').src=src;
    message('eval-save-message','');
    message('eval-draw-message','Drag on the photo to draw a label box.');
    renderLabels();
    el('eval-editor').scrollIntoView({behavior:'smooth',block:'start'});
  }
  async function openExperiment(id) {
    clearTimeout(scoringTimer);
    const version=++scoringVersion;
    try {
      const report=await api('/api/evaluation/runs/'+id);
      if (version!==scoringVersion)return;
      experiment=report;
      for (const key of ['distance','gap','eye']) el('eval-'+key).value=report.thresholds[key];
      renderScores(report);
      if(!el('page-evaluation').hidden)el('eval-results').scrollIntoView({behavior:'smooth',block:'start'});
    } catch(error){message('eval-message',error.message);}
  }
  function renderScores(report) {
    experiment=report;
    el('eval-results').hidden=false;
    el('eval-run-info').textContent=`${report.split} split · ${report.photo_ids.length} photo(s) · ${report.model} · ${formatTime(report.created_utc)} · gallery ${report.gallery_sha256.slice(0,12)} · ${report.methods.full.photos[0]?.title || ''}${report.photo_ids.length>1 ? ' + '+(report.photo_ids.length-1)+' more photo(s)' : ''}`;
    for(const key of ['distance','gap','eye'])el('eval-'+key+'-value').textContent=Number(el('eval-'+key).value).toFixed(2);
    const definitions=[['correct','Correct'],['wrong','Wrong'],['missed','Missed'],['unknown_false_accept','Unknown false accepts'],['unknown_rejected','Unknown rejections'],['extra_predictions','Extra predictions']];
    el('eval-methods').innerHTML=['full','eye'].map(mode=>{
      const result=report.methods[mode];
      return `<article class="eval-method"><h3>${mode==='full'?'Full-face accepted matches':'Eye-only review suggestions'}</h3><p>Recall ${percent(result.recall)} · Precision ${percent(result.precision)}</p><div class="eval-metrics">${definitions.map(([key,label])=>`<div><strong>${result.counts[key]||0}</strong><span>${label}</span></div>`).join('')}</div><p>${result.errors ? `${result.errors} photo(s) unavailable for this method. Excluded from its totals.` : 'All selected photos processed.'}</p></article>`;
    }).join('');
    el('eval-details').innerHTML=['full','eye'].map(mode=>`<details><summary>${mode==='full'?'Full-face':'Eye-only'} results by photo</summary>${report.methods[mode].photos.map(photo=>`<section class="eval-photo-results"><h3>${escapeHTML(photo.title)}</h3>${photo.error?`<p>${escapeHTML(photo.error)}</p>`:`<div class="table-scroll"><table><thead><tr><th>Expected</th><th>Proposed identity</th><th>Outcome</th></tr></thead><tbody>${photo.details.map(row=>`<tr><td>${escapeHTML(row.expected_roll)} ${escapeHTML(row.expected_name)}</td><td>${escapeHTML(row.predicted_roll)} ${escapeHTML(row.predicted_name)||'—'}</td><td>${escapeHTML(outcomeNames[row.outcome])}</td></tr>`).join('')}</tbody></table></div>`}</section>`).join('')}</details>`).join('');
    message('eval-score-message','');
  }
  async function rescore() {
    if (!experiment)return;
    const id=experiment.id, version=++scoringVersion;
    message('eval-score-message','Updating measurements…');
    const query=new URLSearchParams(Object.fromEntries(['distance','gap','eye'].map(key=>[key,el('eval-'+key).value])));
    try {
      const report=await api('/api/evaluation/runs/'+id+'?'+query);
      if(version===scoringVersion)renderScores(report);
    }catch(error){if(version===scoringVersion)message('eval-score-message',error.message);}
  }
  document.querySelector('[data-page="evaluation"]').addEventListener('click',()=>refreshCatalog().catch(error=>message('eval-message',error.message)));
  el('eval-new').addEventListener('click',()=>{if(!busy)el('eval-file').click();});
  el('eval-file').addEventListener('change',async event=>{
    const file=event.target.files[0];event.target.value='';if(!file||busy)return;
    const version=++fileVersion;
    try {const loaded=await readFile(file);if(version!==fileVersion||busy)return;imageData=loaded;showEditor(null,imageData);el('eval-photo-title').value=file.name.slice(0,120);}
    catch(error){message('eval-message',error.message);}
  });
  el('eval-source').addEventListener('load',renderBoxes);
  el('eval-boxes').addEventListener('pointerdown',event=>{
    if(busy||event.button!==0)return;
    dragStart=point(event);dragEnd=dragStart;
    el('eval-boxes').setPointerCapture(event.pointerId);event.preventDefault();
  });
  el('eval-boxes').addEventListener('pointermove',event=>{if(dragStart){dragEnd=point(event);renderBoxes();}});
  el('eval-boxes').addEventListener('pointerup',event=>{
    if(!dragStart)return;
    dragEnd=point(event);
    const box={x:Math.min(dragStart.x,dragEnd.x),y:Math.min(dragStart.y,dragEnd.y),w:Math.abs(dragStart.x-dragEnd.x),h:Math.abs(dragStart.y-dragEnd.y)};
    dragStart=null;dragEnd=null;addBox(box);renderBoxes();
  });
  el('eval-boxes').addEventListener('pointercancel',()=>{dragStart=null;dragEnd=null;renderBoxes();});
  el('eval-box-add').addEventListener('click',()=>addBox(Object.fromEntries(['x','y','w','h'].map(key=>[key,Number(el('eval-'+key).value)]))));
  el('eval-label-list').addEventListener('change',event=>{
    const select=event.target.closest('[data-eval-label]');
    if(select){const row=labels[Number(select.dataset.evalLabel)];if(!select.value.startsWith('saved:')){row.roll_number=select.value;delete row.source_index;}el('eval-complete').checked=false;}
  });
  el('eval-label-list').addEventListener('click',event=>{
    const button=event.target.closest('[data-eval-remove]');if(!button||busy)return;
    labels.splice(Number(button.dataset.evalRemove),1);el('eval-complete').checked=false;renderLabels();
  });
  el('eval-cancel').addEventListener('click',()=>{if(!busy){++fileVersion;el('eval-editor').hidden=true;imageData=null;editing=null;labels=[];}});
  el('eval-save').addEventListener('click',async()=>{
    if(busy)return;
    if(!labels.length||labels.some(row=>!row.roll_number)){message('eval-save-message','Label every box before saving.');return;}
    if(!el('eval-independent').checked||!el('eval-complete').checked){message('eval-save-message','Confirm separate photos and complete labels.');return;}
    setWorking(true);
    try {
      const savedSplit=editing?.split || el('eval-photo-split').value;
      const payload={labels,complete:true};
      if(editing) {await api(`/api/evaluation/photos/${editing.id}/labels`,{...payload,revision:editing.revision});}
      else {await api('/api/evaluation',{...payload,title:el('eval-photo-title').value,split:el('eval-photo-split').value,independent:true,image:imageData});}
      if(el('eval-split-filter').value!==savedSplit){el('eval-split-filter').value=savedSplit;selected.clear();}
      el('eval-editor').hidden=true;imageData=null;editing=null;
      message('eval-message','Labeled photo saved. Select it to compare methods.');
      try {await refreshCatalog();} catch {message('eval-message','Photo saved. Reopen Evaluation to refresh the photo list.');}
    }catch(error){message('eval-save-message',error.message);}
    finally{setWorking(false);}
  });
  el('eval-split-filter').addEventListener('change',()=>{selected.clear();renderCatalog();});
  el('eval-photo-list').addEventListener('change',event=>{
    const input=event.target.closest('[data-eval-photo]');if(!input)return;
    if(input.checked)selected.add(input.dataset.evalPhoto);else selected.delete(input.dataset.evalPhoto);
  });
  el('eval-photo-list').addEventListener('click',async event=>{
    const button=event.target.closest('[data-eval-edit]');if(!button||busy)return;
    const version=++fileVersion;
    try {const record=await api('/api/evaluation/photos/'+button.dataset.evalEdit);if(version!==fileVersion||busy)return;imageData=null;showEditor(record,`/api/evaluation/photos/${record.id}/image`);}
    catch(error){message('eval-message',error.message);}
  });
  el('eval-run').addEventListener('click',async()=>{
    if(busy)return;
    if(!selected.size||selected.size>10){message('eval-message','Select 1–10 labeled photos.');return;}
    clearTimeout(scoringTimer);++scoringVersion;
    setWorking(true);message('eval-message','Comparing both methods… Preparing eye-reference patches can take a minute on the first run.');
    try {
      const report=await api('/api/evaluation/runs',{photo_ids:[...selected]});
      ++scoringVersion;
      for(const key of ['distance','gap','eye'])el('eval-'+key).value=report.thresholds[key];
      renderScores(report);await refreshCatalog();message('eval-message','Experiment saved. Explore thresholds below.');
      if(!el('page-evaluation').hidden)el('eval-results').scrollIntoView({behavior:'smooth',block:'start'});
    }catch(error){message('eval-message',error.message);}
    finally{setWorking(false);}
  });
  el('eval-open-run').addEventListener('click',()=>{const id=el('eval-run-history').value;if(id&&!busy)openExperiment(id);});
  for(const key of ['distance','gap','eye'])el('eval-'+key).addEventListener('input',()=>{
    el('eval-'+key+'-value').textContent=Number(el('eval-'+key).value).toFixed(2);
    ++scoringVersion;clearTimeout(scoringTimer);scoringTimer=setTimeout(rescore,200);
  });
})();
