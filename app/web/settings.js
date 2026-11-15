(() => {
  const keys=['detector','model','cosine_distance_threshold','minimum_gap','default_extra_detection','default_eye_search','live_interval_ms','video_sample_interval_ms','video_required_samples','video_min_face_pixels','video_min_sharpness','default_late_after_minutes','default_start_time','default_end_time','default_directory_view','attendance_target'];
  const numeric=new Set(['cosine_distance_threshold','minimum_gap','live_interval_ms','video_sample_interval_ms','video_required_samples','video_min_face_pixels','video_min_sharpness','default_late_after_minutes','attendance_target']);
  const $s=id=>document.getElementById(id);
  let data=null,dirty=false,loading=false,pending=false,generation=0,applied=null;
  window.getAppPreferences=()=>state?.settings||{};
  window.applySettingsDefaults=config=>{
    const labels={retinaface:'RetinaFace',opencv:'OpenCV',yunet:'YuNet',centerface:'CenterFace',mtcnn:'MTCNN',Facenet512:'FaceNet512'};
    if($s('active-pipeline-label'))$s('active-pipeline-label').textContent=`${labels[config?.detector]||config?.detector||'RetinaFace'} + ${labels[config?.model]||config?.model||'FaceNet512'}`;
    const values={default_extra_detection:Boolean(config?.default_extra_detection),default_eye_search:Boolean(config?.default_eye_search),default_directory_view:config?.default_directory_view||'grid'};
    for(const [key,id] of [['default_extra_detection','extra-detection'],['default_eye_search','eye-search']])if(!applied||applied[key]!==values[key])$s(id).checked=values[key];
    if(!applied||applied.default_directory_view!==values.default_directory_view){directoryListView=values.default_directory_view==='list';if(state)renderStudents();}
    applied=values;updateAdvancedStatus();
  };
  function readForm(){return Object.fromEntries(keys.map(key=>{const input=$s('pref-'+key);return [key,input.type==='checkbox'?input.checked:numeric.has(key)?Number(input.value):input.value];}));}
  function fill(values){for(const key of keys){const input=$s('pref-'+key);if(input.type==='checkbox')input.checked=values[key];else input.value=String(values[key]);}}
  let draftModel=null,draftProfiles={};
  const matchingKeys=['cosine_distance_threshold','minimum_gap'];
  function loadModelProfile(){
    const model=$s('pref-model').value;
    if(!data||draftModel===model)return;
    if(draftModel)draftProfiles[draftModel]={...draftProfiles[draftModel],...Object.fromEntries(matchingKeys.map(key=>[key,Number($s('pref-'+key).value)]))};
    const profile=draftProfiles[model]||{cosine_distance_threshold:.3,minimum_gap:.05,calibrated:false};
    for(const key of matchingKeys)$s('pref-'+key).value=String(profile[key]);
    draftModel=model;$s('settings-confirm-model').checked=false;
  }
  function modelChange(){return Boolean(data)&&$s('pref-model').value!==data.values.model;}
  function describeModels(){
    if(!data)return;
    const model=$s('pref-model').value;
    if(draftModel!==model){$s('settings-confirm-model').checked=false;draftModel=model;}
    for(const [key,items] of [['detector',data.models.detectors],['embedding',data.models.embeddings]]){
      $s(`settings-${key}-count`).textContent=`${items.length} supported ${key==='detector'?'detectors':'embedding models'}`;
      $s(`settings-${key}-description`).textContent=items.find(item=>item.id===$s(key==='detector'?'pref-detector':'pref-model').value)?.description||'';
    }
    $s('settings-model-change').hidden=!modelChange();
    $s('settings-model-change-info').textContent=`Switching from ${data.values.model} to ${model} will rebuild ${data.gallery.templates} registered student templates. Keep this page open; the current gallery stays active until rebuilding succeeds.`;
    $s('settings-save').textContent=modelChange()?'Activate & rebuild templates':'Save project settings';
    const profile=data.model_profiles?.[model];
    const calibrated=Boolean(profile?.calibrated)&&matchingKeys.every(key=>Number($s('pref-'+key).value)===profile[key])&&$s('pref-detector').value===data.values.detector;
    $s('settings-calibration-status').textContent=`${model} · ${calibrated?'Calibration recorded':'Uncalibrated'} — matching values are saved separately for this embedding model. Validate them with independent photos in Evaluation.`;
  }
  function markDirty(){loadModelProfile();dirty=Boolean(data)&&JSON.stringify(readForm())!==JSON.stringify(Object.fromEntries(keys.map(key=>[key,data.values[key]])));if(dirty)$s('settings-model-progress').textContent='';describeModels();window.updateSettingsControls();}
  function paint(result){
    data=result;
    for(const [key,models] of [['detector',result.models.detectors],['model',result.models.embeddings]])$s('pref-'+key).innerHTML=models.map(model=>`<option value="${escapeHTML(model.id)}">${escapeHTML(model.name)}${model.id===(key==='detector'?'retinaface':'Facenet512')?' (Recommended)':''}</option>`).join('');
    fill(result.values);draftModel=result.values.model;draftProfiles=JSON.parse(JSON.stringify(result.model_profiles||{}));draftProfiles[draftModel]={...draftProfiles[draftModel],...Object.fromEntries(matchingKeys.map(key=>[key,result.values[key]]))};$s('settings-confirm-model').checked=false;dirty=false;describeModels();
    $s('settings-gallery-info').textContent=`${result.gallery.templates} registered templates · ${result.gallery.dimensions} embedding dimensions · ${result.gallery.normalization} normalization`;
    renderActive(result.active_scans||[]);
    $s('settings-load-message').textContent='';window.updateSettingsControls();
  }
  function renderActive(active){
    $s('settings-active-scans').hidden=!active.length;
    $s('settings-active-scans').innerHTML=active.length?'<strong>Stop video sampling before changing project settings.</strong><p>Open each active scan’s lecture and choose Stop scan.</p>'+active.map(item=>`<button type="button" class="button secondary" data-settings-lecture="${item.id}">${escapeHTML(item.title)} ↗</button>`).join(''):'';
  }
  async function load(preserve=false){
    if(busy){pending=true;return;}
    const version=++generation;loading=true;window.updateSettingsControls();$s('settings-load-message').textContent='Loading project settings…';
    try{const result=await api('/api/settings');if(version!==generation)return;
      if(preserve&&dirty&&data){data.active_scans=result.active_scans;renderActive(result.active_scans||[]);$s('settings-load-message').textContent=result.revision===data.revision?'':'Project settings changed elsewhere. Your draft is kept; discard and reload to use the latest settings.';}
      else{paint(result);$s('settings-message').textContent='Changes affect future checks. Saved attendance stays unchanged.';}}
    catch(error){if(version===generation)$s('settings-load-message').textContent=error.message;}
    finally{if(version===generation){loading=false;window.updateSettingsControls();}}
  }
  window.updateSettingsControls=()=>{
    const locked=busy||loading||!data;
    $s('settings-fields').disabled=locked;
    $s('settings-save').disabled=locked||!dirty||(modelChange()&&!$s('settings-confirm-model').checked)||Boolean(data?.active_scans?.length)||$s('video-attendance-button').getAttribute('aria-pressed')==='true';
    $s('settings-defaults').disabled=locked;
    $s('settings-reload').disabled=busy||loading;
    $s('settings-reload').textContent=dirty?'Discard & reload ↻':'Reload settings ↻';
    $s('settings-draft-label').textContent=dirty?'Unsaved changes':'Saved settings';
    if(pending&&!busy&&!loading){pending=false;Promise.resolve().then(()=>load(dirty));}
  };
  document.querySelector('[data-page="settings"]').addEventListener('click',()=>void load(dirty));
  $s('settings-reload').addEventListener('click',()=>void load());
  $s('settings-form').addEventListener('input',markDirty);$s('settings-form').addEventListener('change',markDirty);
  $s('settings-defaults').addEventListener('click',()=>{if(!data||busy)return;fill(data.defaults);draftModel=data.defaults.model;$s('settings-confirm-model').checked=false;markDirty();$s('settings-message').textContent='Defaults are loaded into the form. Save to apply them.';});
  $s('settings-form').addEventListener('submit',async event=>{
    event.preventDefault();if(busy||!data||!dirty||loading)return;
    if(modelChange()&&!$s('settings-confirm-model').checked)return;
    const revision=data.revision,values=readForm(),pipelineChanged=values.model!==data.values.model||values.detector!==data.values.detector;
    busy=true;updateControls();
    let polling=true,timer=null;
    async function progress(){
      try{const result=await api('/api/settings/status');if(polling)$s('settings-model-progress').textContent=result.message||'Preparing models…';}catch(_){}
      if(polling)timer=setTimeout(progress,1200);
    }
    if(pipelineChanged){$s('settings-model-progress').textContent='Preparing models. First activation may download weights…';timer=setTimeout(progress,600);}
    try{
      const result=await api('/api/settings',{revision,values,confirm_model_change:$s('settings-confirm-model').checked});paint(result);$s('settings-message').textContent='Project settings saved. Future checks will use these values.';
      $s('settings-model-progress').textContent=pipelineChanged?'Pipeline activated. Test the matching thresholds with independent photos in Evaluation.':'';
      await refreshAfterSave('Project settings saved.');
    }catch(error){$s('settings-message').textContent=error.message;$s('settings-model-progress').textContent='';}
    finally{polling=false;clearTimeout(timer);busy=false;updateControls();}
  });
  $s('settings-active-scans').addEventListener('click',event=>{const button=event.target.closest('[data-settings-lecture]');if(button&&!busy)void openLecture(button.dataset.settingsLecture);});
  function theme(){if($s('settings-theme'))$s('settings-theme').value=document.documentElement.dataset.theme||'light';}
  $s('settings-theme').addEventListener('change',()=>window.setClassroomTheme?.($s('settings-theme').value));
  window.addEventListener('classroom-theme-change',theme);theme();
  if(state?.settings)window.applySettingsDefaults(state.settings);
  window.updateSettingsControls();
})();
