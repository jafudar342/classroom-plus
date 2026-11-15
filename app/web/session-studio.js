/* The session view reflects saved lecture decisions; it never changes attendance. */
(() => {
  const clocks = new Map();
  let clockId = null, renderKey = '', nextTarget = null;
  const text = (id,value) => { $(id).textContent = String(value); };
  const count = value => Math.max(0,Number(value) || 0);
  function tick() {
    const item = captureLecture, id = item?.state === 'draft' ? item.id : null;
    const visible = Boolean(id) && !document.hidden && !$('page-attendance').hidden;
    const timestamp = Date.now();
    if (clockId && (clockId !== id || !visible)) {
      const previous = clocks.get(clockId);
      if (previous && previous.started !== null) { previous.total += Math.max(0,timestamp-previous.started); previous.started = null; }
    }
    clockId = id;
    if (!id) return;
    if (!clocks.has(id)) clocks.set(id,{total:0,started:null});
    const clock = clocks.get(id);
    if (visible && clock.started === null) clock.started = timestamp;
    const seconds = Math.floor((clock.total + (clock.started === null ? 0 : Math.max(0,timestamp-clock.started)))/1000);
    const hours = Math.floor(seconds/3600), minutes = Math.floor(seconds/60)%60;
    const stamp = `${String(minutes).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`;
    text('session-elapsed',hours ? `${String(hours).padStart(2,'0')}:${stamp}` : stamp);
  }
  function timeLabel(value) {
    const date = new Date(value);
    return Number.isFinite(date.getTime()) ? date.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}) : '';
  }
  function activity(item) {
    const students = new Map(item.attendance.map(row=>[row.roll_number,row]));
    const events = [], latest = new Map();
    function student(roll,label,kind,date) {
      const row = students.get(roll); if (!row) return;
      if (kind === 'present' && row.status !== 'Present') return;
      if (kind === 'review' && row.status === 'Present') return;
      const event = {name:row.name,label,kind,date};
      if (!latest.has(roll) || (date || '') >= (latest.get(roll).date || '')) latest.set(roll,event);
    }
    for (const capture of item.captures || []) {
      events.push({name:'Class photo saved',label:`${capture.detections.length} faces found`,kind:'capture',date:capture.created_utc});
      for (const face of capture.detections) {
        const resolution = item.face_resolutions?.[`${capture.id}:${face.face_id}`];
        if (resolution?.action === 'ignore') continue;
        const roll = resolution?.action === 'assign' ? resolution.roll_number : face.decision === 'Matched' ? face.candidate_roll : null;
        if (roll) student(roll,'Marked present · photo','present',resolution?.updated_utc || capture.created_utc);
      }
    }
    for (const scan of item.video_scans || []) {
      for (const track of scan.tracks) {
        if (!track.proposed_roll || track.decision === 'ignored') continue;
        if (track.decision === 'accepted') student(track.proposed_roll,'Confirmed present · video','present',track.reviewed_utc);
        else student(track.proposed_roll,'Video proposal · needs review','review',track.evidence?.at(-1)?.created_utc || scan.started_utc);
      }
    }
    for (const row of item.attendance) {
      if (row.override) student(row.roll_number,row.status === 'Present' ? 'Marked present · teacher' : 'Marked absent · teacher',row.status === 'Present' ? 'present' : 'teacher',row.override.updated_utc);
    }
    for (const entry of item.audit || []) {
      const label = {video_started:'Video sampling started',video_stopped:'Video evidence saved'}[entry.action];
      if (label) events.push({name:label,label:entry.action === 'video_stopped' ? 'Ready for teacher review' : 'Collecting clear views',kind:'capture',date:entry.created_utc});
    }
    events.push(...latest.values());
    events.sort((a,b)=>(b.date || '').localeCompare(a.date || '') || a.name.localeCompare(b.name));
    return events.slice(0,5);
  }
  function setNext(title,description,label,target) {
    text('session-next-title',title); text('session-next-description',description);text('session-next-action',label);
    nextTarget = target;
    $('session-next-action').disabled = busy || !target || $(target).disabled;
  }
  window.updateSessionStudio = () => {
    const item = captureLecture?.state === 'draft' ? captureLecture : null;
    const active = Boolean(item);
    $('session-companion').hidden = !active;
    $('capture-explainer').hidden = active;
    $('capture-sample-card').hidden = active;
    $('attendance-overview').hidden = active;
    $('attendance-context').hidden = active;
    $('lecture-capture-banner').hidden = !active;
    $('page-attendance').classList.toggle('has-session',active);
    tick();
    const sampling = $('video-attendance-button').getAttribute('aria-pressed') === 'true';
    const key = [item?.id,item?.revision,source,Boolean(cameraStream),Boolean(selectedImage),busy,sampling].join(':');
    if (renderKey === key) return;
    renderKey = key;
    $('attendance-heading').innerHTML = active ? 'Your class, in session<span class="heading-dot">.</span>' : 'A clear view of your class<span class="heading-dot">.</span>';
    text('attendance-intro',active ? 'Capture the room. Follow the progress. Finish with confidence.' : 'Register a face. Capture a moment. Bring your attendance into focus.');
    text('capture-panel-title',active ? (source === 'camera' ? 'A live view of your classroom' : 'Bring your class into view') : 'Start with a photo');
    text('capture-panel-note',active ? 'Every capture contributes to this lecture’s attendance.' : 'Upload a class photo or use your webcam.');
    if (!item) return;
    text('lecture-capture-label',item.title);
    text('session-context',`${item.context.class_name} · ${item.context.subject_name} · ${item.lecture_date}`);
    $('session-timetable-note').hidden=!item.schedule;
    if(item.schedule)text('session-timetable-note',`Scheduled ${item.schedule.start_time}–${item.schedule.end_time} · Late after ${item.schedule.late_after_minutes} min · ${item.schedule.timezone}`);
    text('session-mode',sampling ? 'VIDEO SAMPLING' : cameraStream ? 'CAMERA READY' : 'LECTURE OPEN');
    $('lecture-capture-banner').classList.toggle('is-sampling',sampling);
    const summary = item.summary, total = count(summary.students), present = Math.min(total,count(summary.present));
    text('session-present',present); text('session-total',total);
    $('session-progress').max = total || 1; $('session-progress').value = present;
    text('session-percent',`${total ? Math.round(present/total*100) : 0}% of your class`);
    const frames = count(summary.video_frames), captures = count(summary.captures);
    text('session-evidence-count',`${captures} photo${captures===1?'':'s'} · ${frames} video sample${frames===1?'':'s'}${item.schedule&&summary.late?' · '+summary.late+' late':''}`);
    text('session-review-count',count(summary.review));text('session-unseen-count',count(summary.unconfirmed ?? summary.absent));
    const pending = count(summary.pending_faces)+count(summary.video_pending);
    text('session-review-note',pending ? `${pending} face${pending===1?'':'s'} or track${pending===1?'':'s'} still need a decision. Video proposals enter attendance after confirmation.` : 'Progress reflects saved attendance. Check the roster before finalizing.');
    const hasEvidence = captures > 0 || frames > 0;
    const interrupted = !sampling && (item.video_scans || []).some(scan=>scan.state === 'active');
    const phase = sampling || !hasEvidence ? 'capture' : item.can_finalize ? 'finish' : 'review';
    const phases = ['start','capture','review','finish'];
    document.querySelectorAll('[data-studio-step]').forEach(node=>{
      const position = phases.indexOf(node.dataset.studioStep), current = phases.indexOf(phase);
      node.classList.toggle('current',position===current);node.classList.toggle('complete',position<current);
      if (position === current) node.setAttribute('aria-current','step'); else node.removeAttribute('aria-current');
    });
    if (sampling) setNext('Let the camera take a moment.','Pause on each group while clear samples build. Stop when you are ready to review.','Stop video sampling','video-attendance-button');
    else if (interrupted) setNext('Finish the open video scan.','Open the lecture and stop its active scan before reviewing the evidence.','Open video review','lecture-view');
    else if (hasEvidence) setNext(item.can_finalize ? 'Give the roster a final look.' : 'A few decisions bring it together.',item.can_finalize ? 'The lecture is ready. Review the roster, then finalize your attendance sheet.' : 'Confirm proposals and check anyone who was missed or needs review.',item.can_finalize ? 'Review & finish →' : 'Review attendance →','lecture-view');
    else if (source === 'camera') setNext(cameraStream ? 'Ready when your class is.' : 'Bring your classroom into focus.',cameraStream ? 'Start video sampling, or save a single frame with Capture below.' : 'Enable the camera, then pause on each group for several clear views.',cameraStream ? 'Start video attendance' : 'Enable camera',cameraStream ? 'video-attendance-button' : 'start-camera');
    else setNext(selectedImage ? 'Your photo is ready.' : 'Start with a view of the class.',selectedImage ? 'Find the faces and add this photo to the lecture.' : 'Choose a class photo, or switch to Webcam to collect video evidence.',selectedImage ? 'Check this photo →' : 'Choose class photo',selectedImage ? 'recognize-button' : 'upload-area');
    const rows = activity(item);
    const feed = rows.length ? rows.map(row=>`<li class="session-event ${row.kind}"><span class="session-event-icon" aria-hidden="true">${row.kind==='present'?'✓':row.kind==='review'?'?':'◉'}</span><div><strong>${escapeHTML(row.name)}</strong><span>${escapeHTML(row.label)}</span></div><time>${escapeHTML(timeLabel(row.date))}</time></li>`).join('') : '<li class="session-activity-empty"><span aria-hidden="true">◎</span><strong>Your first capture starts the story.</strong><p>Attendance updates and review suggestions will appear here.</p></li>';
    if ($('session-activity').innerHTML !== feed) $('session-activity').innerHTML = feed;
  };
  $('session-next-action').addEventListener('click',()=>{if(!busy && nextTarget && !$(nextTarget).disabled) $(nextTarget).click();});
  window.renderLectureCompletion = item => {
    const done = item.state === 'finalized';
    $('lecture-completion').hidden = !done;
    if (!done) return;
    text('completion-context',`${item.title} · ${item.context.class_name} · ${item.context.subject_name}`);
    $('completion-counts').innerHTML = `<span><strong>${count(item.summary.present)}</strong> present</span><span><strong>${count(item.summary.absent)}</strong> absent</span><span><strong>${count(item.summary.students)}</strong> students</span>`;
    text('completion-saved',`Finalized ${formatTime(item.finalized_utc)} · Attendance is locked and saved on this laptop.`);
    $('completion-download').href = `/api/lectures/${item.id}/attendance.csv`;
  };
  document.addEventListener('visibilitychange',tick);
  setInterval(tick,1000);
  window.updateSessionStudio();
})();
