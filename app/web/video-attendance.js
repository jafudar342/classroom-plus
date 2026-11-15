/* Completion-paced webcam sampling. Only reviewed proposals enter attendance. */
(() => {
  let session = null, timer = null;
  const button = document.getElementById('video-attendance-button');
  const status = document.createElement('p');
  status.className = 'video-sampling-status'; status.setAttribute('role','status'); status.hidden = true;
  document.getElementById('capture-action-bar').append(status);
  function apply(item) {
    if (session?.lecture.id === item.id) session.lecture = item;
    if (captureLecture?.id === item.id) { captureLecture = item; renderCaptureLecture(); }
    if (viewedLecture?.id === item.id) { viewedLecture = item; renderLecture(); }
  }
  window.updateVideoControls = () => {
    button.hidden = source !== 'camera' && !session;
    button.textContent = session ? (session.stopping ? 'Stopping video…' : 'Stop video attendance') : 'Start video attendance';
    button.disabled = session ? session.stopping : busy || live || !cameraStream || !cameraFrameReady($('camera-video')) || !captureLecture || captureLecture.state !== 'draft';
    button.setAttribute('aria-pressed',String(Boolean(session)));
    status.hidden = !session;
    $('lecture-video-scans').querySelectorAll('button').forEach(node=>{node.disabled=busy;});
    if (!session) return;
    for (const id of ['recognize-button','live-button','new-lecture','start-context-lecture','lecture-leave','lecture-view','lecture-add','lecture-reload','lecture-finalize']) $(id).disabled = true;
    status.textContent = session.stopping ? 'Finishing the current sample and saving evidence…' : `Video attendance · ${session.lecture.summary.video_frames || 0} samples · Pause briefly on each group. Stop to review proposals.`;
  };
  async function stop() {
    if (!session) return;
    session.stopping = true; clearTimeout(timer); updateControls();
    if (session.inFlight || !session.id) return;
    if (busy) { timer = setTimeout(stop,500); return; }
    const current = session; busy = true; updateControls();
    try {
      // Reload also recovers safely after an uncertain frame response or another tab's change.
      current.lecture = await api(`/api/lectures/${current.lecture.id}`);
      const result = await api(`/api/lectures/${current.lecture.id}/video/${current.id}/stop`,{revision:current.lecture.revision});
      apply(result.lecture);
      toast('Video saved. Open the lecture to review attendance proposals.');
    } catch(error) { toast(`${error.message} Open the lecture and stop its active scan before finalizing.`,true); }
    finally { if (session === current) session = null; busy = false; updateControls(); }
  }
  window.stopVideoAttendance = () => { void stop(); };
  function frameImage() {
    const video = $('camera-video');
    if (!cameraFrameReady(video)) throw new Error('The camera is not ready.');
    const scale = Math.min(1,1280/Math.max(video.videoWidth,video.videoHeight));
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(video.videoWidth*scale); canvas.height = Math.round(video.videoHeight*scale);
    canvas.getContext('2d').drawImage(video,0,0,canvas.width,canvas.height);
    return canvas.toDataURL('image/jpeg',.94);
  }
  async function sample() {
    const current = session;
    if (!current) return;
    if (current.stopping || !cameraStream || document.hidden || $('page-attendance').hidden || captureLecture?.id !== current.lecture.id) { await stop(); return; }
    if (busy) { timer = setTimeout(sample,500); return; }
    busy = true; current.inFlight = true; updateControls();
    try {
      const result = await api(`/api/lectures/${current.lecture.id}/video/${current.id}/frame`,{
        revision:current.lecture.revision,frame_id:crypto.randomUUID().replaceAll('-',''),image:frameImage()
      });
      apply(result.lecture);
    } catch(error) { current.stopping = true; toast(error.message,true); }
    finally {
      current.inFlight = false; busy = false; updateControls();
      if (current.stopping) await stop(); else timer = setTimeout(sample,current.lecture.video_scans?.find(scan=>scan.id===current.id)?.sample_interval_ms || (window.getAppPreferences?.() || {}).video_sample_interval_ms || 1500);
    }
  }
  button.addEventListener('click',async () => {
    if (session) { await stop(); return; }
    if (busy || !cameraStream || !cameraFrameReady($('camera-video')) || !captureLecture) return;
    stopLive();
    const current = session = {lecture:captureLecture,id:null,stopping:false,inFlight:true};
    busy = true; updateControls();
    try {
      const result = await api(`/api/lectures/${current.lecture.id}/video/start`,{revision:current.lecture.revision});
      current.id = result.scan_id; apply(result.lecture);
    } catch(error) { session = null; toast(error.message,true); }
    finally { current.inFlight = false; busy = false; updateControls(); }
    if (session) { if (current.stopping) await stop(); else await sample(); }
  });
  window.renderVideoAttendance = item => {
    const scans = item.video_scans || [], final = item.state === 'finalized';
    $('lecture-video-scans').innerHTML = scans.length ? scans.map(scan => `<article class="video-scan" data-video-scan="${scan.id}">
      <div class="video-scan-header"><div><strong>${scan.state === 'active' ? 'Sampling active' : 'Saved video scan'}</strong><p>${scan.frame_count} frames · ${scan.empty_frames} without visible faces · ${scan.required_samples} clear samples required</p></div>${!final && scan.state==='active' ? '<button class="button secondary" data-video-action="stop">Stop scan</button>' : ''}</div>
      ${scan.state==='active' ? '<p>Stop sampling to review. If the camera was closed, use Stop scan to finish this session.</p>' : !final && scan.tracks.some(t=>t.decision==='pending'&&!t.proposed_roll) ? '<button class="button secondary" data-video-action="ignore_unverified">Ignore all unverified tracks</button>' : ''}
      <div class="video-tracks">${scan.tracks.map(track => {
        const row = item.attendance.find(row=>row.roll_number===track.proposed_roll);
        const latest = track.observations.at(-1), evidence = track.evidence || [];
        return `<article class="video-track"><img loading="lazy" alt="Best view of video track ${track.id}" src="/api/lectures/${item.id}/video/${scan.id}/tracks/${track.id}/photo?v=${track.best?.frame || 0}"><div><strong>${row ? escapeHTML(row.name)+' · Roll '+escapeHTML(row.roll_number) : 'Unverified face'}</strong><p>Track ${track.id} · ${track.seen} observations · ${escapeHTML(track.decision)}</p><p>${row ? `${evidence.length} consistent clear matches · cosine distances ${evidence.map(e=>Number(e.cosine_distance).toFixed(3)).join(', ')}` : escapeHTML(latest?.reason || 'Needs more clear samples.')}</p>${!final && scan.state==='stopped' ? `<div class="video-track-actions">${track.decision==='pending' ? `${row ? `<button class="button primary" data-video-action="accept" data-track="${track.id}">Confirm present</button>` : ''}<button class="button secondary" data-video-action="ignore" data-track="${track.id}">Ignore</button>` : `<button class="button secondary" data-video-action="reset" data-track="${track.id}">Undo decision</button>`}</div>` : ''}</div></article>`;
      }).join('') || '<p>No face tracks collected. Use another scan or teacher roll call.</p>'}</div></article>`).join('') : '<p class="empty-state">Open this lecture for capture, enable the webcam, then choose Start video attendance. Sampling stays on this laptop.</p>';
  };
  $('lecture-video-scans').addEventListener('click',async event => {
    const control = event.target.closest('[data-video-action]'); if (!control || busy) return;
    const item = viewedLecture, scan = control.closest('[data-video-scan]').dataset.videoScan;
    if (session) { await stop(); return; }
    busy = true; updateControls();
    try {
      const action = control.dataset.videoAction;
      const result = await api(`/api/lectures/${item.id}/video/${scan}/${action==='stop'?'stop':'review'}`,{
        revision:item.revision,action,track_id:control.dataset.track ? Number(control.dataset.track) : undefined
      });
      apply(result.lecture); await refreshAfterSave('Video review saved.');
    } catch(error) { toast(error.message,true); }
    finally { busy = false; updateControls(); }
  });
  document.addEventListener('visibilitychange',()=>{if(document.hidden) void stop();});
  updateControls();
})();
