"use strict";

const $ = (id) => document.getElementById(id);
const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
let state = null;
let viewedLecture = null;
let captureLecture = null;
let selectedCaptureId = null;
let xsrf = "";
let source = "upload";
let selectedImage = null;
let cameraStream = null;
let registrationStream = null;
let registrationImage = null;
let registrationPreview = null;
let selectedFace = null;
let result = null;
let selectedResultFace = null;
let directoryListView = false;
let busy = false;
let live = false;
let liveGeneration = 0;
let liveTimer = null;
let toastTimer = null;
let cameraGeneration = 0;
let registrationCameraGeneration = 0;
let registrationGeneration = 0;
let photoGeneration = 0;
let waitingForFace = false;
let activeProfile = null;
let profileDirty = false;
let registrationQueue = [];
let registrationReturnRoll = null;
let registrationIdentity = null;
let registrationReferenceCount = 0;
let availableCameras = [], preferredCameraId = '', cameraListGeneration = 0, cameraListLoading = false;
let cameraListMessage = 'Enable camera to reveal available camera names.', cameraAccessGranted = false;
let cameraOpening = false, registrationCameraOpening = false;
const pendingCameraRequests = new Map();
const cameraPreferenceKey = 'classroom-attendance-camera';
try { preferredCameraId = localStorage.getItem(cameraPreferenceKey) || ''; } catch { /* Selection still works without storage. */ }
const profileFields = ["roll_number", "name", "department", "course", "semester", "section", "email", "phone", "notes"];
const profileId = (field) => "profile-" + (field === "roll_number" ? "roll" : field);
let selectedClassId = "all-students";
let selectedSubjectId = "";
let activeAcademicClassId = null;
let classEditorId = null;
let classEditorRevision = "";
let enrollment = new Set();
let subjectEditorId = null;
let subjectEditorRevision = "";

function toast(message, error = false) {
  $("toast").textContent = message;
  $("toast").classList.toggle("error", error);
  $("toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $("toast").hidden = true; }, error ? 10000 : 5000);
}

async function localFetch(path, options) {
  try {
    const response = await fetch(path, options);
    $("connection-status").classList.remove("offline");
    $("connection-status").innerHTML = '<span class="pulse-dot"></span> On this laptop';
    return response;
  } catch {
    $("connection-status").classList.add("offline");
    $("connection-status").textContent = "Disconnected";
    throw new Error("The local app is disconnected. Reopen it, then choose Refresh workspace.");
  }
}

async function api(path, payload) {
  const send = () => localFetch(path, payload === undefined ? {} : {
    method: "POST",
    headers: {"Content-Type": "application/json", "X-XSRFToken": xsrf},
    body: JSON.stringify(payload),
  });
  let response = await send();
  // A second tab can be processing a frame while this workspace opens.
  for (let attempt = 0; response.status === 409 && path === "/api/state" && attempt < 6; attempt++) {
    await new Promise((resolve) => setTimeout(resolve, 500));
    response = await send();
  }
  // Jupyter and other localhost apps must not invalidate registration requests.
  // Refresh a stale app token once, without repeating a successful mutation.
  if (response.status === 403 && payload !== undefined) {
    const session = await localFetch("/api/session", {cache: "no-store"});
    if (session.ok) {
      xsrf = (await session.json()).xsrf;
      response = await send();
    }
  }
  let data;
  try { data = await response.json(); }
  catch { throw new Error("The local app did not respond. Check that its terminal is still open."); }
  if (!response.ok) {
    const error = new Error(response.status === 403
      ? "Your browser session changed. Refresh this app tab and try again."
      : data.error || "This request could not be completed.");
    error.code = data.code;
    error.status = response.status;
    throw error;
  }
  return data;
}

async function refreshState() {
  state = await api("/api/state");
  xsrf = state.xsrf;
  window.applySettingsDefaults?.(state.settings);
  $("registered-count").textContent = state.students.filter((student) => student.registered).length;
  $("nav-student-count").textContent = state.students.length;
  $("session-count").textContent = state.session_count ?? state.history.length;
  $("threshold-value").textContent = state.settings.cosine_distance_threshold.toFixed(2);
  $("gap-value").textContent = state.settings.minimum_gap.toFixed(2);
  $("sample-button").disabled = !state.sample_available;
  renderAcademicControls();
  renderStudents();
  renderHistory();
  renderArchives();
  renderClasses();
  renderLectures();
  window.refreshDashboard?.();
  window.refreshTimetable?.();
  $("workspace-date").textContent = new Date().toLocaleDateString(undefined, {weekday: "short", month: "short", day: "numeric"});
}

async function refreshAfterSave(message) {
  // A saved mutation must not be reported as failed if refreshing the UI fails.
  toast(message);
  try { await refreshState(); }
  catch { toast(`${message} Use Refresh workspace if the directory hasn't updated.`); }
}
$("refresh-workspace").addEventListener("click", async () => {
  $("refresh-workspace").disabled = true;
  try { await refreshState(); toast("Workspace is up to date."); }
  catch (error) { toast(error.message, true); }
  finally { $("refresh-workspace").disabled = false; }
});

function navigate(page) {
  stopLive();
  stopCamera();
  document.querySelectorAll(".page").forEach((section) => { section.hidden = section.id !== `page-${page}`; });
  document.querySelectorAll(".nav-item[data-page]").forEach((button) => button.classList.toggle("active", button.dataset.page === page));
  $("breadcrumb").textContent = {settings: "Settings", timetable: "Timetable", about: "About Classroom+", evaluation: "Recognition evaluation", dashboard: "Attendance dashboard", attendance: "Take attendance", students: "Student directory", classes: "Classes & subjects", history: "Photo reports", lectures: "Lecture sessions"}[page];
  window.scrollTo({top: 0});
  window.updateSessionStudio?.();
  window.updateTimetableControls?.();
  window.updateSettingsControls?.();
  updateCameraControls();
}
document.querySelectorAll(".nav-item[data-page]").forEach((button) => button.addEventListener("click", () => navigate(button.dataset.page)));
$("about-start").addEventListener("click", () => navigate("attendance"));

function updateControls() {
  const contextReady = Boolean(captureLecture) || selectedClassId === "all-students" || Boolean(selectedSubjectId);
  $("recognize-button").disabled = busy || !(source === "camera" ? cameraStream && cameraFrameReady($("camera-video")) : selectedImage) || live || !contextReady;
  $("live-button").disabled = busy && !live || !cameraStream || !contextReady || Boolean(captureLecture);
  $("live-button").setAttribute("aria-pressed", String(live));
  $("live-button").textContent = live ? "Stop live check" : "Start live check";
  $("recognize-button").innerHTML = source === "camera" ? "Capture & save attendance →" : "✧ Check attendance →";
  if(captureLecture) $("recognize-button").textContent = source === "camera" ? "Capture & add to lecture →" : "Add photo to lecture →";
  $("processing-status").hidden = !busy && !live;
  $("processing-status").querySelector("span:last-child").textContent = waitingForFace && live
    ? "Waiting for a face… Live checking will continue automatically."
    : live ? "Checking this frame… Live checks are not saved." : "Finding faces and comparing embeddings…";
  $("source-note").textContent = source === "camera" ? (live ? "Live preview · Stop to save a capture." : "Capture a frame to save a report. Start a lecture to enable video attendance.") : "Clear, front-facing photos work best.";
  if(captureLecture) $("source-note").textContent="Add captures one at a time. Review the lecture when you are finished.";
  for (const id of ["register-no-photo", "register-upload", "register-camera-start", "register-capture", "detect-register", "register-roll", "register-name", "add-reference", "change-photo"]) {
    $(id).disabled = busy || Boolean(registrationIdentity && ["register-roll", "register-name", "add-reference"].includes(id));
  }
  $("finish-registration").disabled = busy;
  $("skip-register-photo").disabled = busy;
  $("keep-registering").disabled = busy;
  $("sample-button").disabled = busy || !state?.sample_available;
  $("save-student").disabled = busy || !registrationPreview || selectedFace === null;
  for (const id of ["save-profile", "profile-add-photo", "add-custom-field", "show-delete-student", "confirm-delete-student"]) {
    $(id).disabled = busy || (id === "confirm-delete-student" && $("delete-roll").value !== activeProfile?.roll_number);
  }
  $("profile-form").querySelectorAll("input, textarea").forEach((input) => { input.disabled = busy; });
  $("custom-fields").querySelectorAll("button").forEach((button) => { button.disabled = busy; });
  $("attendance-class").disabled = busy || Boolean(captureLecture);
  $("attendance-subject").disabled = busy || Boolean(captureLecture) || selectedClassId === "all-students";
  $("register-class").disabled = busy || $("add-reference").checked;
  for (const id of ["save-class", "save-subject", "enroll-shown", "enroll-clear"]) $(id).disabled = busy;
  $("class-form").querySelectorAll("input").forEach((input) => { input.disabled = busy; });
  $("subject-form").querySelectorAll("input, select").forEach((input) => { input.disabled = busy || (input.id === "subject-class" && Boolean(subjectEditorId)); });
  for(const id of ["new-lecture","start-context-lecture","lecture-add","lecture-reload","lectures-back","lecture-leave","lecture-view"]) $(id).disabled=busy;
  $("lecture-finalize").disabled=busy||!viewedLecture?.can_finalize;
  $("finalize-submit").disabled=busy||!$("finalize-confirm").checked;
  $("lecture-workspace").querySelectorAll('input,select,button[data-save-row],button[data-save-face]').forEach(node=>{node.disabled=busy;});
  for (const id of ['selected-face-confirm','selected-face-ignore','selected-face-reset','selected-face-student','selected-face-note']) $(id).disabled=busy;
  $("upload-area").setAttribute("aria-disabled", busy);
  window.updateVideoControls?.();
  window.updateSessionStudio?.();
  window.updateTimetableControls?.();
  window.updateSettingsControls?.();
  updateCameraControls();
}

function setSource(value) {
  window.stopVideoAttendance?.();
  source = value;
  stopLive();
  if (value !== "camera") stopCamera();
  $("tab-upload").classList.toggle("active", value === "upload");
  $("tab-camera").classList.toggle("active", value === "camera");
  $("tab-upload").setAttribute("aria-selected", value === "upload");
  $("tab-camera").setAttribute("aria-selected", value === "camera");
  $("upload-area").hidden = value !== "upload" || Boolean(selectedImage);
  $("upload-preview").hidden = value !== "upload" || !selectedImage;
  $("camera-area").hidden = value !== "camera";
  $("camera-device-controls").hidden = value !== "camera";
  if (value === 'camera') void refreshCameraList();
  $("live-button").hidden = value !== "camera";
  updateControls();
}
$("tab-upload").addEventListener("click", () => setSource("upload"));
$("tab-camera").addEventListener("click", () => setSource("camera"));

function readFile(file) {
  return new Promise((resolve, reject) => {
    if (!file || !["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
      reject(new Error("Choose a JPG, PNG, or WebP image.")); return;
    }
    if (file.size > 15_000_000) { reject(new Error("Choose an image smaller than 15 MB.")); return; }
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error("The file could not be read."));
    reader.readAsDataURL(file);
  });
}
async function chooseClassPhoto(file) {
  if (busy) { toast("Wait for the current check to finish before changing the photo."); return; }
  const generation = ++photoGeneration;
  try {
    const image = await readFile(file);
    if (generation !== photoGeneration) return;
    selectedImage = image;
    $("input-image").src = selectedImage;
    $("selected-file-name").textContent = file.name;
    setSource("upload");
  } catch (error) { toast(error.message, true); }
}
$("upload-area").addEventListener("click", () => $("class-file").click());
$("upload-area").addEventListener("keydown", (event) => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); $("class-file").click(); } });
$("change-photo").addEventListener("click", () => $("class-file").click());
$("class-file").addEventListener("change", (event) => { if (event.target.files[0]) chooseClassPhoto(event.target.files[0]); event.target.value = ""; });
for (const type of ["dragenter", "dragover", "dragleave", "drop"]) {
  $("upload-area").addEventListener(type, (event) => {
    event.preventDefault();
    $("upload-area").classList.toggle("drag", ["dragenter", "dragover"].includes(type));
    if (type === "drop" && event.dataTransfer.files[0]) chooseClassPhoto(event.dataTransfer.files[0]);
  });
}
$("sample-button").addEventListener("click", async () => {
  try {
    const response = await localFetch("/api/sample");
    if (!response.ok) throw new Error("The sample photo could not be loaded.");
    await chooseClassPhoto(new File([await response.blob()], "synthetic-classroom.png", {type: "image/png"}));
    toast(captureLecture ? "Sample loaded. Choose Add photo to lecture." : "Sample photo loaded. Choose Check attendance to process it.");
  } catch (error) { toast(error.message, true); }
});

function cameraSelectionLocked() {
  return busy || cameraOpening || registrationCameraOpening || live || $('video-attendance-button').getAttribute?.('aria-pressed') === 'true';
}
function updateCameraControls() {
  const locked = cameraSelectionLocked();
  for (const prefix of ['attendance','registration']) {
    $(prefix+'-camera-select').disabled = locked || cameraListLoading;
    $(prefix+'-camera-refresh').disabled = busy || cameraListLoading || cameraOpening || registrationCameraOpening;
    $(prefix+'-camera-message').textContent = live || $('video-attendance-button').getAttribute?.('aria-pressed') === 'true'
      ? 'Stop the live check or video attendance before switching cameras.' : cameraListMessage;
  }
  $('start-camera').disabled = busy || cameraOpening || registrationCameraOpening;
  $('register-camera-start').disabled = busy || cameraOpening || registrationCameraOpening;
  $('register-capture').disabled = busy || registrationCameraOpening || !registrationStream || !cameraFrameReady($('register-video'));
  $('stop-camera').hidden = !cameraStream && !cameraOpening;
  $('stop-camera').textContent = cameraOpening ? 'Cancel camera request' : 'Turn off camera';
  $('register-camera-stop').hidden = !registrationStream && !registrationCameraOpening;
  $('register-camera-stop').textContent = registrationCameraOpening ? 'Cancel camera request' : 'Turn off camera';
}
function renderCameraList() {
  const missing = preferredCameraId && !availableCameras.some(device=>device.deviceId===preferredCameraId);
  const options = '<option value="">System default camera</option>' + (missing
    ? `<option value="${escapeHTML(preferredCameraId)}">Saved camera · reconnect or choose another</option>` : '')
    + availableCameras.map((device,index)=>`<option value="${escapeHTML(device.deviceId)}">${escapeHTML(device.label || 'Camera '+(index+1))}</option>`).join('');
  for (const prefix of ['attendance','registration']) {
    $(prefix+'-camera-select').innerHTML = options;
    $(prefix+'-camera-select').value = preferredCameraId;
  }
  updateCameraControls();
}
async function refreshCameraList() {
  const generation = ++cameraListGeneration;
  if (document.hidden) { cameraListLoading=false;updateCameraControls();return; }
  if (!navigator.mediaDevices?.enumerateDevices) {
    cameraListLoading = false;
    cameraListMessage = 'Camera listing is unavailable here. Try a supported browser on localhost; the system default may still work.';
    renderCameraList();return;
  }
  cameraListLoading = true;updateCameraControls();
  let timer;
  try {
    const devices = await Promise.race([navigator.mediaDevices.enumerateDevices(),new Promise((_,reject)=>{
      timer=setTimeout(()=>reject(new Error('Camera discovery timed out.')),5000);
    })]);
    if (generation !== cameraListGeneration) return;
    const seen = new Set();
    availableCameras = devices.filter(device=>device.kind==='videoinput' && device.deviceId && !seen.has(device.deviceId) && seen.add(device.deviceId));
    const named = availableCameras.some(device=>device.label);
    cameraListMessage = named ? `${availableCameras.length} camera${availableCameras.length===1?'':'s'} available. Select one for attendance and registration.`
      : 'Enable camera or Use webcam once to allow access and reveal camera names. Then refresh if needed.';
    if (cameraAccessGranted && !devices.some(device=>device.kind==='videoinput'))
      cameraListMessage = 'No cameras are currently available. Connect a camera, then choose Refresh cameras.';
    if ((cameraAccessGranted || named) && preferredCameraId && !availableCameras.some(device=>device.deviceId===preferredCameraId))
      cameraListMessage = 'The saved camera is unavailable. Reconnect it or choose another camera; it will not be replaced silently.';
    for (const [stream,stop] of [[cameraStream,stopCamera],[registrationStream,stopRegistrationCamera]]) {
      const id = stream?.getVideoTracks()[0]?.getSettings?.().deviceId;
      if (cameraAccessGranted && (named || !devices.some(device=>device.kind==='videoinput')) && id && !availableCameras.some(device=>device.deviceId===id)) {
        stop();cameraListMessage = 'The active camera disconnected. Choose another camera and enable it again.';
      }
    }
  } catch (error) {
    if (generation === cameraListGeneration) cameraListMessage = 'Could not refresh cameras. Check browser permission and try Refresh cameras again.';
  } finally {
    clearTimeout(timer);
    if (generation === cameraListGeneration) { cameraListLoading = false;renderCameraList(); }
  }
}
async function chooseCamera(event) {
  if (cameraSelectionLocked() || cameraListLoading) { renderCameraList();return; }
  const next = event.target.value;
  if (next===preferredCameraId) return;
  const attendanceActive = Boolean(cameraStream), registrationActive = Boolean(registrationStream);
  preferredCameraId = next;
  try { localStorage.setItem(cameraPreferenceKey,next); } catch { /* Session-only selection remains usable. */ }
  if (attendanceActive) stopCamera();
  if (registrationActive) stopRegistrationCamera();
  renderCameraList();
  if (attendanceActive) await startAttendanceCamera();
  else if (registrationActive) await startRegistrationCamera();
}
for (const prefix of ['attendance','registration']) {
  $(prefix+'-camera-select').addEventListener('change',chooseCamera);
  $(prefix+'-camera-refresh').addEventListener('click',()=>void refreshCameraList());
}
navigator.mediaDevices?.addEventListener?.('devicechange',()=>void refreshCameraList());

function cameraError(error) {
  if (["NotAllowedError", "PermissionDeniedError"].includes(error.name)) return "Camera permission was denied. Allow camera access for localhost in your browser, then try again.";
  if (error.name === "NotFoundError") return preferredCameraId ? 'The selected camera was not found. Reconnect it, or refresh cameras and choose another.' : "No webcam was found. Connect a camera, or upload a photo.";
  if (error.name === "NotReadableError") return "Your camera is busy. Close other apps using it and try again.";
  if (error.name === 'OverconstrainedError') return 'The selected camera is unavailable or unsupported. Refresh cameras and choose another one.';
  return error.message || "Could not open your camera. You can upload a photo instead.";
}
function cancelCameraRequest(video) {
  pendingCameraRequests.get(video)?.();
}
async function openCamera(video, isCurrent = () => true) {
  if (!navigator.mediaDevices?.getUserMedia) throw new Error("Camera access requires localhost in a supported browser. Open the app at http://localhost:8765.");
  if (!isCurrent()) throw new DOMException('Camera request cancelled.','AbortError');
  cancelCameraRequest(video);
  let abandoned = false, stream = null, timer, rejectCancellation;
  const cancellation = new Promise((_,reject)=>{rejectCancellation=reject;});
  function release() {
    stream?.getTracks().forEach(track=>track.stop());
    if (stream && video.srcObject===stream) video.srcObject=null;
  }
  function cancel(error = new DOMException('Camera request cancelled.','AbortError')) {
    abandoned=true;release();rejectCancellation(error);
  }
  pendingCameraRequests.set(video,cancel);
  timer=setTimeout(()=>cancel(new Error('The camera did not become ready. Check browser permission, close other camera apps, and try again.')),15000);
  const acquisition=(async()=>{
    try {
      stream=await navigator.mediaDevices.getUserMedia({video:{width:{ideal:1920},height:{ideal:1080},
        ...(preferredCameraId?{deviceId:{exact:preferredCameraId}}:{facingMode:'user'})},audio:false});
      if (abandoned || !isCurrent()) throw new DOMException('Camera request cancelled.','AbortError');
      video.srcObject=stream;
      await video.play();
      if (abandoned || !isCurrent()) throw new DOMException('Camera request cancelled.','AbortError');
      const track=stream.getVideoTracks?.()[0];
      if (!track || track.readyState==='ended') throw new Error('The camera disconnected before its preview became ready.');
      return stream;
    } catch (error) { release();throw error; }
  })();
  try {
    const active=await Promise.race([acquisition,cancellation]);
    cameraAccessGranted=true;void refreshCameraList();return active;
  } finally {
    clearTimeout(timer);
    if (pendingCameraRequests.get(video)===cancel) pendingCameraRequests.delete(video);
  }
}

function stopCamera() {
  cancelCameraRequest($("camera-video"));
  window.stopVideoAttendance?.();
  cameraGeneration++;
  stopLive();
  const stoppedStream = cameraStream;
  cameraStream = null;
  stoppedStream?.getTracks().forEach((track) => track.stop());
  $("camera-video").srcObject = null;
  $("camera-video").classList.remove("playing");
  $("camera-placeholder").hidden = false;
  $("camera-status").hidden = true;
  $("stop-camera").hidden = true;
  updateControls();
}
async function startAttendanceCamera() {
  if (busy || cameraOpening || registrationCameraOpening || cameraStream) return;
  const generation = ++cameraGeneration;
  const isCurrent = () => generation === cameraGeneration && source === "camera" && !document.hidden && !$("page-attendance").hidden && !$("register-dialog").open;
  cameraOpening = true;updateCameraControls();
  try {
    const stream = await openCamera($("camera-video"), isCurrent);
    if (!isCurrent()) { stream.getTracks().forEach((track) => track.stop()); return; }
    cameraStream = stream;
    $("camera-video").classList.add("playing");
    $("camera-placeholder").hidden = true;
    $("camera-status").hidden = false;
    $("stop-camera").hidden = false;
    for (const event of ['mute','unmute']) stream.getVideoTracks()[0].addEventListener(event,updateControls);
    stream.getVideoTracks()[0].addEventListener("ended", () => {
      if (cameraStream !== stream) return;
      stopCamera();void refreshCameraList();toast("Camera disconnected. Choose a connected camera and enable it again, or upload a photo.", true);
    });
    updateControls();
  } catch (error) { if (error.name !== "AbortError" && isCurrent()) toast(cameraError(error), true); }
  finally { cameraOpening = false;updateCameraControls(); }
}
$("start-camera").addEventListener("click",startAttendanceCamera);
$("stop-camera").addEventListener("click", stopCamera);

function cameraFrameReady(video) {
  const tracks=video.srcObject?.getVideoTracks?.() || [];
  return Boolean(video.videoWidth && video.videoHeight && video.readyState>=2 && tracks.length
    && tracks.every(track=>track.readyState!=='ended' && !track.muted));
}
function snapshot(video) {
  if (!cameraFrameReady(video)) throw new Error("The camera is not ready. Wait a moment and try again.");
  const canvas = document.createElement("canvas");
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  canvas.getContext("2d").drawImage(video, 0, 0);
  return canvas.toDataURL("image/jpeg", 0.94);
}

async function recognize(save = true, generation = liveGeneration) {
  if (busy) return;
  busy = true;
  updateControls();
  try {
    const image = source === "camera" ? snapshot($("camera-video")) : selectedImage;
    if (!image) throw new Error("Choose a photo or enable your camera first.");
    if(captureLecture && !save) throw new Error("Use Capture to add a photo to this lecture.");
    const captured = captureLecture ? await api(`/api/lectures/${captureLecture.id}/capture`, {image, eye_search:$("eye-search").checked, extra_detection:$("extra-detection").checked, source:source === "camera" ? "webcam" : "upload", revision:captureLecture.revision}) : null;
    if(captured) { captureLecture=captured.lecture; viewedLecture=captured.lecture; selectedCaptureId=captured.capture_report.lecture_capture.capture_id; renderLecture();renderCaptureLecture(); }
    const response = captured ? captured.capture_report : await api("/api/recognize", {image, save, eye_search:$("eye-search").checked, extra_detection:$("extra-detection").checked, source: source === "camera" ? "webcam" : "upload", class_id: selectedClassId, subject_id: selectedSubjectId});
    if (!save && (!live || generation !== liveGeneration)) return;
    waitingForFace = false;
    renderResult(response);
    if (save) {
      await refreshAfterSave(captureLecture ? "Capture added. Review the lecture to finalize attendance." : "Photo report saved. Use a lecture to confirm and finalize attendance.");
      $("results-panel").scrollIntoView({behavior: "smooth", block: "start"});
    }
  } catch (error) {
    if (!save && live && generation === liveGeneration && error.code === "face_not_found") {
      waitingForFace = true;
      return;
    }
    if (save || live) toast(error.message, true);
    if (!save) stopLive();
  } finally { busy = false; updateControls(); }
}
$("recognize-button").addEventListener("click", () => recognize(true));
function stopLive() {
  live = false;
  waitingForFace = false;
  liveGeneration++;
  clearTimeout(liveTimer);
}
$("live-button").addEventListener("click", async () => {
  if (live) { stopLive(); updateControls(); return; }
  live = true;
  const generation = ++liveGeneration;
  updateControls();
  async function tick() {
    if (!live || generation !== liveGeneration) return;
    await recognize(false, generation);
    if (live && generation === liveGeneration) liveTimer = setTimeout(tick, (window.getAppPreferences?.() || {}).live_interval_ms || 2500);
  }
  await tick();
});

function formatTime(value) {
  return new Date(value).toLocaleString(undefined, {dateStyle: "medium", timeStyle: "short"});
}
function renderResult(value) {
  result = value;
  selectedResultFace = null;
  $("selected-face-panel").hidden = true;
  $("face-overlays").innerHTML = "";
  const summary = value.summary;
  $("results-panel").hidden = false;
  $("result-image").src = value.image || `/api/reports/${value.run_id}/annotated.jpg`;
  $("result-subtitle").textContent = `${summary.class_name || "All students"} · ${summary.subject_name || "General attendance"} · ${summary.faces} faces checked in ${summary.seconds}s · ${value.lecture_capture ? "Added to lecture · review to finalize" : value.run_id ? "Saved " + formatTime(summary.created_utc) : "Live check · not saved"}`;
  $("result-stats").innerHTML = [[summary.present,"Present","Present"],[summary.absent,"Absent","Absent"],[summary.unconfirmed ?? value.attendance.filter(row => row.status === "Unconfirmed").length,"Unconfirmed","Unconfirmed"],[summary.review ?? value.attendance.filter(row => row.status === "Review").length,"Needs review","Review"],[summary.unknown_faces,"Unknown faces","Unknown"]].map(([count,label,status]) => `<button class="result-stat" data-roster-status="${status}" aria-pressed="false"><strong>${count}</strong><span>${label}</span></button>`).join("");
  $("download-image").href = value.run_id ? `/api/reports/${value.run_id}/annotated.jpg` : value.image;
  $("download-csv").hidden = !value.run_id;
  $("download-detections").hidden = !value.run_id;
  if (value.run_id) {
    $("download-csv").href = `/api/reports/${value.run_id}/attendance.csv`;
    $("download-detections").href = `/api/reports/${value.run_id}/detections.csv`;
  }
  renderAttendance();
  renderFaceOverlays();
  renderFaceButtons();
  const number = (value) => value === null || value === undefined ? "—" : value.toFixed(4);
  $("detection-table").innerHTML = value.detections.map((face) => `<tr><td>${face.face_id}</td><td>${escapeHTML(face.candidate_roll)} · ${escapeHTML(face.candidate_name)}</td><td>${number(face.cosine_distance)}</td><td>${number(face.euclidean_distance)}</td><td>${number(face.gap)}</td><td><span class="status-pill ${face.decision}">${face.decision}</span></td><td>${escapeHTML(face.reason)}</td></tr>`).join("");
}
function renderAttendance() {
  if (!result) return;
  const filter = $("roster-filter").value;
  $("result-stats").querySelectorAll('[data-roster-status]').forEach(button => button.setAttribute('aria-pressed',String(button.dataset.rosterStatus === filter)));
  const rows = result.attendance.filter((row) => filter === "All" || row.status === filter);
  $("attendance-list").innerHTML = rows.length ? rows.map((row) => `<button type="button" class="attendance-row ${result.detections.some(face => face.face_id === selectedResultFace && face.candidate_roll === row.roll_number) ? 'face-selected' : ''}" data-result-roll="${escapeHTML(row.roll_number)}"><div><strong>${escapeHTML(row.name)}</strong><small>Roll ${escapeHTML(row.roll_number)}</small></div><span class="status-pill ${row.status}">${row.status}</span></button>`).join("") : '<p class="empty-state">No students in this category.</p>';
}
$("roster-filter").addEventListener("change", renderAttendance);

function renderStudents() {
  if (!state) return;
  const search = $("student-search").value.toLowerCase().trim();
  const classes = academicData().classes;
  const priorClass = $("directory-class").value;
  $("directory-class").innerHTML = '<option value="">All classes</option>' + classes.map(group => `<option value="${group.id}">${escapeHTML(group.name)}</option>`).join('');
  $("directory-class").value = classes.some(group => group.id === priorClass) ? priorClass : '';
  const group = classes.find(group => group.id === $("directory-class").value);
  const students = state.students.filter(student => !group || group.student_rolls.includes(student.roll_number)).filter((student) => `${student.name} ${student.roll_number} ${student.department || ""} ${student.course || ""} ${student.section || ""}`.toLowerCase().includes(search));
  const sort = $("directory-sort").value;
  students.sort((a,b) => {
    if (sort === 'name') return a.name.localeCompare(b.name) || a.roll_number.localeCompare(b.roll_number,undefined,{numeric:true});
    if (sort === 'references' && a.references !== b.references) return b.references-a.references;
    if (sort === 'unregistered' && a.registered !== b.registered) return Number(a.registered)-Number(b.registered);
    return a.roll_number.localeCompare(b.roll_number,undefined,{numeric:true});
  });
  $("student-grid").classList.toggle('student-list-view',directoryListView);
  $("directory-grid-view").setAttribute('aria-pressed',String(!directoryListView));
  $("directory-list-view").setAttribute('aria-pressed',String(directoryListView));
  $("directory-count").textContent = `${students.length} student${students.length === 1 ? "" : "s"}`;
  $("student-grid").innerHTML = students.length ? students.map((student) => `<article class="student-card"><div class="student-photo"><span aria-hidden="true">${escapeHTML(student.name.slice(0, 1).toUpperCase())}</span><img src="/api/students/${encodeURIComponent(student.roll_number)}/photo" alt="Reference for ${escapeHTML(student.name)}" loading="lazy"></div><h3>${escapeHTML(student.name)}</h3><p>Roll ${escapeHTML(student.roll_number)} · ${student.references} reference${student.references === 1 ? "" : "s"}</p>${student.course || student.department ? `<p class="student-course">${escapeHTML(student.course || student.department)}</p>` : ""}<span class="status-pill ${student.registered ? "Present" : "Review"}">${student.registered ? "Registered" : "Camera-free check-in"}</span><div class="student-card-actions"><button data-manage-roll="${escapeHTML(student.roll_number)}">Manage profile ↗</button><button data-add-roll="${escapeHTML(student.roll_number)}" aria-label="Add photos for ${escapeHTML(student.name)}">＋ Photos</button></div></article>`).join("") : '<div class="empty-state">No students match your search.</div>';
  $("student-grid").querySelectorAll("img").forEach((image) => image.addEventListener("error", () => { image.hidden = true; }, {once: true}));
}
$("student-search").addEventListener("input", renderStudents);
$("directory-class").addEventListener("change", renderStudents);
$("directory-sort").addEventListener("change", renderStudents);
$("directory-grid-view").addEventListener("click", () => {directoryListView=false;renderStudents();});
$("directory-list-view").addEventListener("click", () => {directoryListView=true;renderStudents();});
$("student-grid").addEventListener("click", (event) => {
  const manage = event.target.closest("[data-manage-roll]");
  if (manage) { openProfile(manage.dataset.manageRoll); return; }
  const button = event.target.closest("[data-add-roll]");
  if (!button) return;
  const student = state.students.find((row) => row.roll_number === button.dataset.addRoll);
  openRegistration(student);
});
function renderHistory() {
  const classFilter = $("history-class-filter").value || "all";
  const subjectFilter = $("history-subject-filter").value || "all";
  const sessions = state.history.filter((session) => (classFilter === "all" || (session.class_id || "all-students") === classFilter) && (subjectFilter === "all" || session.subject_id === subjectFilter));
  $("history-list").innerHTML = sessions.length ? sessions.map((session) => `<article class="history-card"><img src="/api/reports/${session.run_id}/annotated.jpg" alt="Session preview" loading="lazy"><div><h3>${escapeHTML(session.class_name || "All students")} · ${escapeHTML(session.subject_name || "General attendance")}</h3><p>${escapeHTML(formatTime(session.created_utc))} · ${session.present} present · ${session.faces} faces · ${session.source === "webcam" ? "Webcam capture" : "Uploaded photo"}</p></div><button class="button secondary" data-open-run="${session.run_id}">View session ↗</button><a class="button secondary" href="/api/reports/${session.run_id}/attendance.csv">↓ CSV</a></article>`).join("") : '<div class="empty-state"><h2>No sessions here yet.</h2><p>Saved attendance will appear here for the selected class and subject.</p></div>';
}
$("history-list").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-open-run]");
  if (!button) return;
  try {
    const report = await api(`/api/reports/${button.dataset.openRun}/result.json`);
    leaveCaptureLecture();
    navigate("attendance");
    renderResult(report);
    $("results-panel").scrollIntoView({behavior:"smooth", block:"start"});
  } catch (error) { toast(error.message, true); }
});

function stopRegistrationCamera() {
  cancelCameraRequest($("register-video"));
  registrationCameraGeneration++;
  const stoppedStream = registrationStream;
  registrationStream = null;
  stoppedStream?.getTracks().forEach((track) => track.stop());
  $("register-video").srcObject = null;
  $("register-camera-area").hidden = true;
  updateCameraControls();
}
function clearRegistrationSelection() {
  registrationPreview = null;
  selectedFace = null;
  $("face-selection").hidden = true;
  $("face-options").replaceChildren();
  $("save-student").disabled = true;
  $("registration-quality").hidden = true;
  $("registration-quality").replaceChildren();
  updateRegistrationGuide();
}
function registrationMessage(message, error = false) {
  $("registration-message").textContent = message;
  $("registration-message").classList.toggle("error", error);
}
function updateRegistrationGuide() {
  $("registration-progress").textContent = `${registrationReferenceCount} reference${registrationReferenceCount === 1 ? "" : "s"} saved · ${registrationReferenceCount >= 3 ? "keep useful variation" : "aim for 3"}`;
  const quality = registrationPreview?.faces?.find((face) => face.index === selectedFace)?.quality;
  const warning = quality?.status === "retake";
  $("save-student").textContent = warning ? "Save despite warnings →" : $("add-reference").checked ? "Add reference →" : "Register student →";
  $("registration-quality").hidden = !quality;
  if (quality) $("registration-quality").innerHTML = `<h4>${warning ? "Retake recommended" : "Basic quality checks passed"}</h4><ul>${quality.checks.map((check) => `<li class="${check.ok ? "quality-pass" : "quality-warning"}"><strong>${check.ok ? "✓" : "!"} ${escapeHTML(check.label)}</strong><span>${check.ok ? "Looks usable" : escapeHTML(check.tip)}</span></li>`).join("")}</ul><p>Advisory checks only. Confirm the correct person before saving${warning ? "; you can save despite these warnings if needed" : ""}.</p>`;
}
function finishRegistration() {
  const returnRoll = registrationReturnRoll;
  $("register-dialog").close();
  if (returnRoll) void openProfile(returnRoll);
}
$("finish-registration").addEventListener("click", finishRegistration);
function openRegistration(student = null) {
  if (busy) { toast("Wait for the current photo to finish processing."); return; }
  stopCamera();
  registrationGeneration++;
  stopRegistrationCamera();
  $("register-form").reset();
  registrationIdentity = null;
  registrationReferenceCount = student?.references || 0;
  $("finish-registration").hidden = true;
  $("skip-register-photo").hidden = true;
  $("keep-registering").checked = true;
  renderCameraList();
  void refreshCameraList();
  registrationImage = null;
  registrationQueue = [];
  registrationReturnRoll = null;
  clearRegistrationSelection();
  $("register-photo-area").hidden = true;
  $("detect-register").hidden = true;
  registrationMessage("");
  if (student) {
    $("register-roll").value = student.roll_number;
    $("register-name").value = student.name;
    $("add-reference").checked = true;
  }
  $("save-student").textContent = student ? "Add reference →" : "Register student →";
  $("registration-title").textContent = student ? "Add reference photos" : "Register a student";
  $("register-upload").textContent = "↑ Choose photos";
  $("register-file").multiple = true;
  $("register-class").value = student ? "" : selectedClassId === "all-students" ? "" : selectedClassId;
  $("register-class").disabled = Boolean(student);
  $("register-no-photo").hidden = Boolean(student);
  $("register-dialog").showModal();
  updateControls();
}
document.querySelectorAll(".register-open").forEach((button) => button.addEventListener("click", () => openRegistration()));
$("close-register").addEventListener("click", () => $("register-dialog").close());
$("register-dialog").addEventListener("close", () => { registrationGeneration++; registrationQueue = []; registrationIdentity = null; clearRegistrationSelection(); stopRegistrationCamera(); });
$("add-reference").addEventListener("change", () => {
  const adding = $("add-reference").checked;
  $("register-no-photo").hidden = adding;
  $("save-student").textContent = adding ? "Add reference →" : "Register student →";
  $("registration-title").textContent = adding ? "Add reference photos" : "Register a student";
  $("register-upload").textContent = "↑ Choose photos";
  $("register-file").multiple = true;
  updateRegistrationGuide();
  $("register-class").disabled = adding;
});
$("register-upload").addEventListener("click", () => $("register-file").click());
function setRegistrationImage(image) {
  registrationGeneration++;
  registrationImage = image;
  $("skip-register-photo").hidden = registrationQueue.length === 0;
  clearRegistrationSelection();
  stopRegistrationCamera();
  $("register-photo").src = image;
  $("register-photo-area").hidden = false;
  $("detect-register").hidden = false;
  registrationMessage("Photo ready. Find faces, then confirm the correct student.");
}
$("skip-register-photo").addEventListener("click", () => {
  if (busy || !registrationQueue.length) return;
  setRegistrationImage(registrationQueue.shift());
  registrationMessage("Photo skipped. Find faces in the next photo to continue.");
});
$("register-file").addEventListener("change", async (event) => {
  const generation = ++registrationGeneration;
  try {
    if (event.target.files[0]) {
      const files = Array.from(event.target.files);
      if (files.length > 10 || files.reduce((sum, file) => sum + file.size, 0) > 50_000_000) throw new Error("Choose up to 10 photos with a combined size below 50 MB.");
      const images = await Promise.all(files.map(readFile));
      if (generation === registrationGeneration && $("register-dialog").open) {
        registrationQueue = images.slice(1);
        setRegistrationImage(images[0]);
        if (registrationQueue.length) registrationMessage(`${files.length} photos selected. Confirm and save each face in turn.`);
      }
    }
  }
  catch (error) { registrationMessage(error.message, true); }
  event.target.value = "";
});
async function startRegistrationCamera() {
  if (busy || cameraOpening || registrationCameraOpening) return;
  registrationCameraOpening = true;updateCameraControls();
  clearRegistrationSelection();
  registrationQueue = [];
  registrationImage = null;
  registrationGeneration++;
  stopRegistrationCamera();
  const generation = ++registrationCameraGeneration;
  const isCurrent = () => generation === registrationCameraGeneration && $("register-dialog").open && !document.hidden;
  try {
    $("register-camera-area").hidden = false;
    $("register-photo-area").hidden = true;
    $("detect-register").hidden = true;
    const stream = await openCamera($("register-video"), isCurrent);
    if (!isCurrent()) { stream.getTracks().forEach((track) => track.stop()); return; }
    registrationStream = stream;
    for (const event of ['mute','unmute']) stream.getVideoTracks()[0].addEventListener(event,updateControls);
    stream.getVideoTracks()[0].addEventListener('ended',()=>{
      if (registrationStream !== stream) return;
      stopRegistrationCamera();void refreshCameraList();registrationMessage('Camera disconnected. Choose another camera and select Use webcam again.',true);
    });
    registrationMessage("Look at the camera, then capture a clear photo.");
  } catch (error) { if (error.name !== "AbortError" && isCurrent()) { stopRegistrationCamera(); registrationMessage(cameraError(error), true); } }
  finally { registrationCameraOpening = false;updateCameraControls(); }
}
$("register-camera-start").addEventListener("click",startRegistrationCamera);
$("register-camera-stop").addEventListener("click",stopRegistrationCamera);
$("register-capture").addEventListener("click", () => {
  try { setRegistrationImage(snapshot($("register-video"))); }
  catch (error) { registrationMessage(error.message, true); }
});
$("detect-register").addEventListener("click", async () => {
  if (busy || !registrationImage) return;
  const generation = registrationGeneration;
  const image = registrationImage;
  busy = true;
  updateControls();
  clearRegistrationSelection();
  $("detect-register").disabled = true;
  registrationMessage("Finding faces… The first request may take a moment.");
  try {
    const preview = await api("/api/register/preview", {image});
    if (generation !== registrationGeneration || !$("register-dialog").open) return;
    registrationPreview = preview;
    $("face-selection").hidden = false;
    $("face-options").innerHTML = registrationPreview.faces.map((face) => `<button type="button" class="face-option" data-face-index="${face.index}" aria-pressed="false"><img src="${face.image}" alt="Detected face ${face.index + 1}">Face ${face.index + 1}<span class="face-quality-badge">${face.quality?.status === "retake" ? "Retake advised" : "Select to review"}</span></button>`).join("");
    registrationMessage(`${registrationPreview.faces.length} face${registrationPreview.faces.length === 1 ? "" : "s"} found. Select the student to confirm.`);
  } catch (error) { if (generation === registrationGeneration && $("register-dialog").open) registrationMessage(error.message, true); }
  finally { busy = false; $("detect-register").disabled = false; updateControls(); }
});
$("face-options").addEventListener("click", (event) => {
  const button = event.target.closest("[data-face-index]");
  if (!button) return;
  selectedFace = Number(button.dataset.faceIndex);
  document.querySelectorAll(".face-option").forEach((option) => {
    const selected = Number(option.dataset.faceIndex) === selectedFace;
    option.classList.toggle("selected", selected);
    option.setAttribute("aria-pressed", selected);
  });
  $("save-student").disabled = false;
  updateRegistrationGuide();
});
$("register-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy || !registrationPreview || selectedFace === null) return;
  const generation = registrationGeneration;
  const returnRoll = registrationReturnRoll;
  busy = true;
  updateControls();
  $("save-student").disabled = true;
  registrationMessage("Saving reference and student embedding…");
  try {
    const saved = await api("/api/register", {
      roll_number: $("register-roll").value.trim(), name: $("register-name").value.trim(),
      add_reference: $("add-reference").checked, preview_id: registrationPreview.preview_id, face_index: selectedFace,
      class_id: $("add-reference").checked ? "" : $("register-class").value,
      quality_acknowledged: registrationPreview.faces?.find((face) => face.index === selectedFace)?.quality?.status === "retake",
    });
    if (generation !== registrationGeneration || !$("register-dialog").open) {
      await refreshAfterSave(`Reference saved for ${saved.name}.`);
      return;
    }
    registrationIdentity = {roll_number: saved.roll_number, name: saved.name};
    registrationReferenceCount = saved.reference_count ?? registrationReferenceCount + 1;
    $("register-roll").value = saved.roll_number;
    $("register-name").value = saved.name;
    $("add-reference").checked = true;
    $("register-class").disabled = true;
    $("register-no-photo").hidden = true;
    $("registration-title").textContent = "Build the reference set";
    $("finish-registration").hidden = false;
    updateRegistrationGuide();
    if (registrationQueue.length) {
      const next = registrationQueue.shift();
      setRegistrationImage(next);
      registrationMessage(`Reference saved. Next photo ready (${registrationQueue.length + 1} remaining). Find faces to continue.`);
      await refreshAfterSave(`Reference saved for ${saved.name}.`);
    } else if ($("keep-registering").checked) {
      registrationImage = null;
      clearRegistrationSelection();
      $("register-photo-area").hidden = true;
      $("detect-register").hidden = true;
      registrationMessage(`Reference saved. ${registrationReferenceCount < 3 ? "Add a different clear photo next, or choose Done to finish." : "Your reference set is ready to review. Add more useful variation or choose Done."}`);
      await refreshAfterSave(`Reference saved for ${saved.name}.`);
    } else {
      const returnToProfile = generation === registrationGeneration && $("register-dialog").open && returnRoll;
      $("register-dialog").close();
      await refreshAfterSave(`${saved.name} · Roll ${saved.roll_number} registered successfully.`);
      if (returnToProfile) { busy = false; await openProfile(saved.roll_number); }
    }
  } catch (error) { registrationMessage(error.message, true); $("save-student").disabled = false; }
  finally { busy = false; updateControls(); }
});

function profileMessage(message, error = false) {
  $("profile-message").textContent = message;
  $("profile-message").classList.toggle("error", error);
}

function addCustomField(field = {label: "", value: ""}) {
  if ($("custom-fields").querySelectorAll(".custom-field-row").length >= 20) { profileMessage("You can add up to 20 custom fields.", true); return; }
  const row = document.createElement("div");
  row.className = "custom-field-row";
  row.innerHTML = `<input class="custom-label" maxlength="60" placeholder="Field label, e.g. Batch" aria-label="Custom field label" required value="${escapeHTML(field.label)}"><input class="custom-value" maxlength="500" placeholder="Value" aria-label="Custom field value" value="${escapeHTML(field.value)}"><button type="button" class="icon-button remove-custom-field" aria-label="Remove custom field">×</button>`;
  $("custom-fields").append(row);
}

function populateProfile(student) {
  activeProfile = student;
  profileDirty = false;
  for (const field of profileFields) $(profileId(field)).value = student[field] || "";
  $("custom-fields").replaceChildren();
  for (const field of student.custom_fields || []) addCustomField(field);
  $("profile-photo-count").textContent = `${student.photos.length} photo${student.photos.length === 1 ? "" : "s"} stored · ${student.references} effective reference${student.references === 1 ? "" : "s"}`;
  $("profile-photos").innerHTML = student.photos.length ? student.photos.map((photo, index) => `<figure><img src="/api/students/${encodeURIComponent(student.roll_number)}/photos/${encodeURIComponent(photo.filename)}" alt="Reference photo ${index + 1} for ${escapeHTML(student.name)}" loading="lazy"><figcaption>Reference ${index + 1}</figcaption></figure>`).join("") : '<p>No reference photos stored. Add a photo to enable recognition.</p>';
  $("delete-confirmation").hidden = true;
  $("delete-roll").value = "";
  $("delete-roll-label").textContent = student.roll_number;
  profileMessage("");
}

async function openProfile(roll) {
  if (busy) { toast("Please wait for the current operation to finish."); return; }
  stopCamera();
  busy = true;
  updateControls();
  try {
    const student = await api(`/api/students/${encodeURIComponent(roll)}`);
    populateProfile(student);
    $("profile-dialog").showModal();
  } catch (error) { toast(error.message, true); }
  finally { busy = false; updateControls(); }
}

$("close-profile").addEventListener("click", () => $("profile-dialog").close());
$("profile-dialog").addEventListener("close", () => { activeProfile = null; profileDirty = false; });
$("profile-form").addEventListener("input", () => { profileDirty = true; });
$("add-custom-field").addEventListener("click", () => { addCustomField(); profileDirty = true; });
$("custom-fields").addEventListener("click", (event) => {
  const button = event.target.closest(".remove-custom-field");
  if (button) { button.closest(".custom-field-row").remove(); profileDirty = true; }
});

$("profile-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy || !activeProfile) return;
  const originalRoll = activeProfile.roll_number;
  const payload = {revision: activeProfile.revision, custom_fields: Array.from($("custom-fields").querySelectorAll(".custom-field-row")).map((row) => ({label: row.querySelector(".custom-label").value, value: row.querySelector(".custom-value").value}))};
  for (const field of profileFields) payload[field] = $(profileId(field)).value.trim();
  busy = true;
  updateControls();
  profileMessage("Saving student details…");
  try {
    const saved = await api(`/api/students/${encodeURIComponent(originalRoll)}/update`, payload);
    if ($("profile-dialog").open && activeProfile?.roll_number === originalRoll) { populateProfile(saved); profileMessage("Changes saved."); }
    await refreshAfterSave("Student details saved.");
  } catch (error) { if ($("profile-dialog").open) profileMessage(error.message, true); else toast(error.message, true); }
  finally { busy = false; updateControls(); }
});

$("profile-add-photo").addEventListener("click", () => {
  if (busy || !activeProfile) return;
  if (profileDirty) { profileMessage("Save your changes before adding photos.", true); return; }
  const student = activeProfile;
  $("profile-dialog").close();
  openRegistration(student);
  registrationReturnRoll = student.roll_number;
  registrationMessage("Choose one or several photos, or use the webcam. Confirm the student's face in each photo.");
});

$("show-delete-student").addEventListener("click", () => { $("delete-confirmation").hidden = false; $("delete-roll").value = ""; updateControls(); $("delete-confirmation").scrollIntoView({behavior: "smooth", block: "nearest"}); $("delete-roll").focus(); });
$("cancel-delete-student").addEventListener("click", () => { $("delete-confirmation").hidden = true; });
$("delete-roll").addEventListener("input", updateControls);
$("confirm-delete-student").addEventListener("click", async () => {
  if (busy || !activeProfile || $("delete-roll").value !== activeProfile.roll_number) return;
  const student = activeProfile;
  busy = true;
  updateControls();
  profileMessage("Moving this student to Recently deleted…");
  try {
    await api(`/api/students/${encodeURIComponent(student.roll_number)}/delete`, {confirmation: $("delete-roll").value, revision: student.revision});
    $("profile-dialog").close();
    await refreshAfterSave(`${student.name} removed from recognition. You can restore them from Recently deleted.`);
  } catch (error) { profileMessage(error.message, true); }
  finally { busy = false; updateControls(); }
});

function renderArchives() {
  const archived = state?.archived_students || [];
  $("archive-count").textContent = archived.length;
  $("archive-shortcut-count").textContent = archived.length;
  $("archive-list").innerHTML = archived.length ? archived.map((student) => `<div class="archived-row"><div><strong>${escapeHTML(student.name)}</strong><small>Roll ${escapeHTML(student.roll_number)} · Deleted ${escapeHTML(formatTime(student.deleted_utc))}</small></div><button class="button secondary" data-restore-id="${student.archive_id}">Restore student</button></div>`).join("") : '<p class="archive-empty">No deleted students.</p>';
}

$("archive-shortcut").addEventListener("click", () => {
  $("archive-panel").open = true;
  $("archive-panel").scrollIntoView({behavior: "smooth", block: "start"});
});

$("archive-list").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-restore-id]");
  if (!button || busy) return;
  busy = true;
  button.disabled = true;
  updateControls();
  try {
    const student = await api("/api/students/restore", {archive_id: button.dataset.restoreId});
    await refreshAfterSave(`${student.name} restored, including their reference photos and face template.`);
  } catch (error) { toast(error.message, true); }
  finally { busy = false; button.disabled = false; updateControls(); }
});

function academicData() {
  return state?.academics || {classes: [], subjects: [], revision: ""};
}

function renderAcademicControls() {
  const data = academicData();
  if (selectedClassId !== "all-students" && !data.classes.some((group) => group.id === selectedClassId)) {
    selectedClassId = "all-students";
    selectedSubjectId = "";
  }
  $("attendance-class").innerHTML = '<option value="all-students">All students · demo / general</option>' + data.classes.map((group) => `<option value="${group.id}">${escapeHTML(group.name)}</option>`).join("");
  $("attendance-class").value = selectedClassId;
  const subjects = data.subjects.filter((subject) => subject.class_id === selectedClassId);
  if (!subjects.some((subject) => subject.id === selectedSubjectId)) selectedSubjectId = subjects[0]?.id || "";
  $("attendance-subject").innerHTML = selectedClassId === "all-students" ? '<option value="">General attendance</option>'
    : subjects.length ? subjects.map((subject) => `<option value="${subject.id}">${escapeHTML(subject.name)}${subject.code ? " · " + escapeHTML(subject.code) : ""}</option>`).join("")
      : '<option value="">Add a subject first</option>';
  $("attendance-subject").value = selectedSubjectId;
  const group = data.classes.find((group) => group.id === selectedClassId);
  const enrolled = group ? state.students.filter((student) => group.student_rolls.includes(student.roll_number)) : state.students;
  $("registered-count").textContent = enrolled.filter((student) => student.registered).length;
  $("registered-label").textContent = group ? "Registered in this class" : "Registered students";
  $("context-note").textContent = group ? `${enrolled.length} enrolled · ${subjects.length} subject${subjects.length === 1 ? "" : "s"}${subjects.length ? "" : " · Add a subject to begin"}` : "General attendance across your whole directory";
  const registrationClass = $("register-class").value;
  $("register-class").innerHTML = '<option value="">All students only</option>' + data.classes.map((group) => `<option value="${group.id}">${escapeHTML(group.name)}</option>`).join("");
  $("register-class").value = data.classes.some((group) => group.id === registrationClass) ? registrationClass : "";
  renderHistoryFilters();
  renderCaptureLecture();
  updateControls();
}

function changeAttendanceContext() {
  stopLive();
  if(captureLecture)return;
  selectedClassId = $("attendance-class").value;
  selectedSubjectId = $("attendance-subject").value;
  result = null;
  $("results-panel").hidden = true;
  renderAcademicControls();
}
$("attendance-class").addEventListener("change", changeAttendanceContext);
$("attendance-subject").addEventListener("change", changeAttendanceContext);
$("manage-classes").addEventListener("click", () => {
  if (selectedClassId !== "all-students") activeAcademicClassId = selectedClassId;
  renderClasses();
  navigate("classes");
});

function renderHistoryFilters() {
  const data = academicData();
  const classValue = $("history-class-filter").value || "all";
  const subjectValue = $("history-subject-filter").value || "all";
  $("history-class-filter").innerHTML = '<option value="all">All classes</option><option value="all-students">All students · general</option>' + data.classes.map((group) => `<option value="${group.id}">${escapeHTML(group.name)}</option>`).join("");
  $("history-class-filter").value = ["all", "all-students", ...data.classes.map((group) => group.id)].includes(classValue) ? classValue : "all";
  const subjects = data.subjects.filter((subject) => $("history-class-filter").value === "all" || subject.class_id === $("history-class-filter").value);
  $("history-subject-filter").innerHTML = '<option value="all">All subjects</option>' + subjects.map((subject) => `<option value="${subject.id}">${escapeHTML(subject.name)}${subject.code ? " · " + escapeHTML(subject.code) : ""}</option>`).join("");
  $("history-subject-filter").value = subjects.some((subject) => subject.id === subjectValue) ? subjectValue : "all";
}
$("history-class-filter").addEventListener("change", () => { renderHistoryFilters(); renderHistory(); });
$("history-subject-filter").addEventListener("change", renderHistory);

function renderClasses() {
  const data = academicData();
  if (!data.classes.some((group) => group.id === activeAcademicClassId)) activeAcademicClassId = data.classes[0]?.id || null;
  $("class-list").innerHTML = data.classes.length ? data.classes.map((group) => `<button class="class-list-item ${group.id === activeAcademicClassId ? "selected" : ""}" data-class-id="${group.id}"><strong>${escapeHTML(group.name)}</strong><small>${group.student_rolls.length} enrolled · ${data.subjects.filter((subject) => subject.class_id === group.id).length} subject${data.subjects.filter((subject) => subject.class_id === group.id).length === 1 ? "" : "s"}</small></button>`).join("") : '<p class="academic-empty">No classes yet. Create one to organize your students.</p>';
  const group = data.classes.find((group) => group.id === activeAcademicClassId);
  if (!group) {
    $("class-detail").innerHTML = '<div class="empty-state"><h2>Your next class starts here.</h2><p>Create a class, enroll its students, and add the subjects you teach.</p></div>';
    return;
  }
  const subjects = data.subjects.filter((subject) => subject.class_id === group.id);
  const students = state.students.filter((student) => group.student_rolls.includes(student.roll_number));
  $("class-detail").innerHTML = `<div class="class-detail-header"><div><div class="eyebrow">CLASS WORKSPACE</div><h2>${escapeHTML(group.name)}</h2><p>${escapeHTML([group.department, group.semester, group.section].filter(Boolean).join(" · ")) || "Your class roster and subjects"}</p></div><button class="button secondary" data-edit-class="${group.id}">Edit class & roster</button></div><div class="class-summary"><span><strong>${students.length}</strong> enrolled students</span><span><strong>${subjects.length}</strong> subject${subjects.length === 1 ? "" : "s"}</span></div><div class="class-roster-chips">${students.slice(0, 8).map((student) => `<span>${escapeHTML(student.name)} <small>· ${escapeHTML(student.roll_number)}</small></span>`).join("")}${students.length > 8 ? `<span>＋ ${students.length - 8} more</span>` : ""}${students.length ? "" : '<p>No students enrolled. Use Edit class & roster to add students.</p>'}</div><div class="profile-section-title"><h3>Subjects</h3><button class="button secondary" data-add-subject="${group.id}">＋ Add subject</button></div><div class="subject-list">${subjects.length ? subjects.map((subject) => `<article class="subject-row"><div><strong>${escapeHTML(subject.name)}</strong><small>${escapeHTML([subject.code, subject.teacher].filter(Boolean).join(" · ")) || "No subject code or teacher added"}</small></div><button class="text-button" data-edit-subject="${subject.id}">Edit subject</button></article>`).join("") : '<p class="academic-empty">Add a subject to start taking attendance for this class.</p>'}</div><button class="button primary" data-use-class="${group.id}" ${subjects.length && students.length ? "" : "disabled"}>Take attendance for this class →</button>`;
}

$("class-list").addEventListener("click", (event) => {
  const button = event.target.closest("[data-class-id]");
  if (button) { activeAcademicClassId = button.dataset.classId; renderClasses(); }
});
$("class-detail").addEventListener("click", (event) => {
  const edit = event.target.closest("[data-edit-class]");
  const add = event.target.closest("[data-add-subject]");
  const subject = event.target.closest("[data-edit-subject]");
  const use = event.target.closest("[data-use-class]");
  if (edit) openClassEditor(edit.dataset.editClass);
  else if (add) openSubjectEditor(add.dataset.addSubject);
  else if (subject) {
    const record = academicData().subjects.find((item) => item.id === subject.dataset.editSubject);
    if (record) openSubjectEditor(record.class_id, record.id);
  } else if (use) {
    if(busy)return;
    captureLecture=null;
    selectedClassId = use.dataset.useClass;
    selectedSubjectId = "";
    result = null;
    $("results-panel").hidden = true;
    renderAcademicControls();
    navigate("attendance");
  }
});

function openClassEditor(id = null) {
  if (busy || !state) { toast("Please wait for the current operation to finish."); return; }
  const data = academicData();
  const group = data.classes.find((group) => group.id === id);
  classEditorId = group?.id || null;
  classEditorRevision = data.revision;
  enrollment = new Set(group?.student_rolls || []);
  $("class-dialog-title").textContent = group ? "Edit class & roster" : "Create class";
  for (const field of ["name", "department", "semester", "section"]) $("class-" + field).value = group?.[field] || "";
  $("enrollment-search").value = "";
  $("class-message").textContent = "";
  renderEnrollment();
  $("class-dialog").showModal();
}
$("new-class").addEventListener("click", () => openClassEditor());
$("close-class").addEventListener("click", () => $("class-dialog").close());

function enrollmentMatches() {
  const search = $("enrollment-search").value.toLowerCase().trim();
  return (state?.students || []).filter((student) => `${student.name} ${student.roll_number} ${student.course || ""}`.toLowerCase().includes(search));
}
function renderEnrollment() {
  const students = enrollmentMatches();
  $("enrollment-count").textContent = `${enrollment.size} selected`;
  $("enrollment-list").innerHTML = students.length ? students.map((student) => `<label class="enrollment-row"><input type="checkbox" data-enroll-roll="${escapeHTML(student.roll_number)}" ${enrollment.has(student.roll_number) ? "checked" : ""}><span><strong>${escapeHTML(student.name)}</strong><small>Roll ${escapeHTML(student.roll_number)}</small></span><small>${student.registered ? "Face ready" : "Needs a photo"}</small></label>`).join("") : '<p class="academic-empty">No students match this search.</p>';
}
$("enrollment-search").addEventListener("input", renderEnrollment);
$("enrollment-list").addEventListener("change", (event) => {
  const input = event.target.closest("[data-enroll-roll]");
  if (!input) return;
  if (input.checked) enrollment.add(input.dataset.enrollRoll); else enrollment.delete(input.dataset.enrollRoll);
  $("enrollment-count").textContent = `${enrollment.size} selected`;
});
$("enroll-shown").addEventListener("click", () => { for (const student of enrollmentMatches()) enrollment.add(student.roll_number); renderEnrollment(); });
$("enroll-clear").addEventListener("click", () => { enrollment.clear(); renderEnrollment(); });
$("class-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy) return;
  const payload = {id: classEditorId, revision: classEditorRevision, student_rolls: Array.from(enrollment)};
  for (const field of ["name", "department", "semester", "section"]) payload[field] = $("class-" + field).value.trim();
  busy = true;
  updateControls();
  $("class-message").textContent = "Saving class and enrollment…";
  $("class-message").classList.remove("error");
  try {
    const saved = await api("/api/classes/save", payload);
    state.academics = saved.academics;
    activeAcademicClassId = saved.class.id;
    $("class-dialog").close();
    renderAcademicControls();
    renderClasses();
    await refreshAfterSave(`${saved.class.name} saved.`);
  } catch (error) { $("class-message").textContent = error.message; $("class-message").classList.add("error"); }
  finally { busy = false; updateControls(); }
});

function openSubjectEditor(classId, id = null) {
  if (busy) { toast("Please wait for the current operation to finish."); return; }
  const data = academicData();
  const subject = data.subjects.find((subject) => subject.id === id);
  subjectEditorId = subject?.id || null;
  subjectEditorRevision = data.revision;
  $("subject-dialog-title").textContent = subject ? "Edit subject" : "Add subject";
  $("subject-class").innerHTML = data.classes.map((group) => `<option value="${group.id}">${escapeHTML(group.name)}</option>`).join("");
  $("subject-class").value = subject?.class_id || classId;
  $("subject-class").disabled = Boolean(subject);
  for (const field of ["name", "code", "teacher"]) $("subject-" + field).value = subject?.[field] || "";
  $("subject-message").textContent = "";
  $("subject-dialog").showModal();
}
$("close-subject").addEventListener("click", () => $("subject-dialog").close());
$("subject-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy) return;
  const payload = {id: subjectEditorId, revision: subjectEditorRevision, class_id: $("subject-class").value};
  for (const field of ["name", "code", "teacher"]) payload[field] = $("subject-" + field).value.trim();
  busy = true;
  updateControls();
  $("subject-message").textContent = "Saving subject…";
  $("subject-message").classList.remove("error");
  try {
    const saved = await api("/api/subjects/save", payload);
    state.academics = saved.academics;
    activeAcademicClassId = saved.subject.class_id;
    $("subject-dialog").close();
    renderAcademicControls();
    renderClasses();
    await refreshAfterSave(`${saved.subject.name} saved.`);
  } catch (error) { $("subject-message").textContent = error.message; $("subject-message").classList.add("error"); }
  finally { busy = false; updateControls(); }
});

document.addEventListener("visibilitychange", () => { if (document.hidden) { stopCamera(); stopRegistrationCamera(); } else void refreshCameraList(); });
window.addEventListener("pagehide", () => { stopCamera(); stopRegistrationCamera(); });
function renderLectures() {
  const lectures = state?.lectures || [];
  $("lecture-list").innerHTML = lectures.length ? lectures.map(item => `<article class="panel lecture-card"><div><span class="status-pill ${item.state === 'finalized' ? 'Present' : 'Review'}">${item.state === 'finalized' ? 'Finalized' : 'Draft'}</span><h2>${escapeHTML(item.title)}</h2><p>${escapeHTML(item.context.class_name)} · ${escapeHTML(item.context.subject_name)}</p><small>${escapeHTML(item.lecture_date)} · ${escapeHTML(item.lecture_time)} · ${item.summary.captures} captures</small></div><div><strong>${item.summary.present} / ${item.summary.students}</strong><p>students present</p><button class="button secondary" data-open-lecture="${item.id}">Open lecture ↗</button></div></article>`).join('') : '<div class="panel empty-state">Start your first lecture to combine captures into one attendance sheet.</div>';
}
function lectureSubjects() {
  const id = $("lecture-new-class").value;
  const subjects = academicData().subjects.filter(row => row.class_id === id);
  $("lecture-new-subject").innerHTML = id === 'all-students' ? '<option value="">General attendance</option>' : subjects.length ? subjects.map(row => `<option value="${row.id}">${escapeHTML(row.name)}</option>`).join('') : '<option value="">Add a subject in Classes & subjects first</option>';
  $("lecture-new-subject").disabled = id === 'all-students';
  $("lecture-create").disabled = busy || (id !== 'all-students' && !subjects.length);
}
function newLecture() {
  if (busy) return;
  $("lecture-form").reset();
  $("lecture-new-class").innerHTML = '<option value="all-students">All students · general</option>' + academicData().classes.map(row => `<option value="${row.id}">${escapeHTML(row.name)}</option>`).join('');
  $("lecture-new-class").value = selectedClassId;
  lectureSubjects();
  if (selectedSubjectId) $("lecture-new-subject").value = selectedSubjectId;
  const local = new Date();
  const padded = number => String(number).padStart(2,'0');
  $("lecture-new-date").value = `${local.getFullYear()}-${padded(local.getMonth()+1)}-${padded(local.getDate())}`;
  $("lecture-new-time").value = `${padded(local.getHours())}:${padded(local.getMinutes())}`;
  $("lecture-zone").textContent = `Time zone: ${Intl.DateTimeFormat().resolvedOptions().timeZone}`;
  $("lecture-message").textContent = '';
  $("lecture-dialog").showModal();
}
async function openLecture(id) {
  if (busy) return;
  try {
    viewedLecture = await api(`/api/lectures/${id}`);
    if (captureLecture?.id === id) {
      captureLecture = viewedLecture.state === "draft" ? viewedLecture : null;
      renderAcademicControls();
    }
    selectedCaptureId = viewedLecture.captures[0]?.id || null;
    renderLecture();
    navigate('lectures');
    updateControls();
  } catch(error) { toast(error.message,true); }
}
function renderLecture() {
  const item = viewedLecture;
  if (!item) return;
  const final = item.state === 'finalized';
  $("roll-call-panel").hidden = final;
  $("roll-call-search").value = "";
  $("roll-call-results").replaceChildren();
  $("lecture-list").hidden = true;
  $("lecture-workspace").hidden = false;
  $("new-lecture").hidden = true;
  $("lecture-title").textContent = item.title;
  $("lecture-state").textContent = final ? 'Finalized · locked' : 'Draft';
  $("lecture-state").className = `status-pill ${final ? 'Present' : 'Review'}`;
  $("lecture-context").textContent = `${item.context.class_name} · ${item.context.subject_name} · ${item.lecture_date} at ${item.lecture_time} (${item.timezone})`;
  $("lecture-schedule-note").hidden=!item.schedule;
  if(item.schedule) $("lecture-schedule-note").textContent=`Scheduled ${item.schedule.start_time}–${item.schedule.end_time} · Late after ${item.schedule.late_after_minutes} minutes · ${item.schedule.timezone}. Arrival markers use first recorded evidence; backfilled dates are not assessed.`;
  $("lecture-add").hidden = final;
  $("lecture-finalize").hidden = final;
  $("lecture-finalize").disabled = busy || !item.can_finalize;
  $("lecture-csv").hidden = !final;
  $("lecture-csv").href = `/api/lectures/${item.id}/attendance.csv`;
  $("lecture-audit").href = `/api/lectures/${item.id}/audit.csv`;
  $("lecture-stats").innerHTML = [[item.summary.present,'Present'],[item.summary.absent,'Absent'],[item.summary.unconfirmed || 0,'Unconfirmed'],[item.summary.review,'Students to review'],[item.summary.pending_faces+(item.summary.video_pending || 0),'Faces / tracks to review']].map(([count,label]) => `<div class="result-stat"><strong>${count}</strong><span>${label}</span></div>`).join('');
  $("lecture-blockers").textContent = final ? 'Final attendance is locked and ready to download.' : item.blockers.length ? item.blockers.join(' ') : 'Ready to finalize. Check the roster before locking attendance.';
  $("lecture-rows").innerHTML = item.attendance.map(row => `<tr data-lecture-roll="${escapeHTML(row.roll_number)}"><td><strong>${escapeHTML(row.name)}</strong><small>Roll ${escapeHTML(row.roll_number)}</small></td><td><span class="status-pill ${row.status}">${row.status}</span>${row.arrival_status ? `<small class="arrival-marker ${row.arrival_status==='Late'?'arrival-late':''}" title="${escapeHTML(row.first_seen_utc ? 'First recorded: '+formatTime(row.first_seen_utc) : 'Arrival time not assessed')}">${escapeHTML(row.arrival_status)}</small>` : ''}</td><td>${row.capture_count}</td><td>${final ? escapeHTML(row.source) : `<select aria-label="Attendance correction for ${escapeHTML(row.name)}" data-row-status><option value="auto" ${!row.override?'selected':''}>Automatic</option><option ${row.override?.status==='Present'?'selected':''}>Present</option><option ${row.override?.status==='Absent'?'selected':''}>Absent</option></select>`}</td><td>${final ? escapeHTML(row.note) : `<input data-row-reason aria-label="Correction reason for ${escapeHTML(row.name)}" maxlength="500" placeholder="Reason for correction" value="${escapeHTML(row.override?.reason || '')}">`}</td><td>${final ? '' : '<button class="button secondary" data-save-row>Save</button>'}</td></tr>`).join('');
  $("lecture-captures").innerHTML = item.captures.length ? item.captures.map((capture,index) => `<button class="lecture-capture ${capture.id===selectedCaptureId?'selected':''}" data-select-capture="${capture.id}"><img alt="Lecture capture ${index+1}" src="/api/lectures/${item.id}/captures/${capture.id}/image?v=${item.revision}"><strong>Capture ${index+1}</strong><small>${capture.summary.faces} faces · ${escapeHTML(capture.source)}</small></button>`).join('') : '<p class="empty-state">No captures yet. Add a photo or use the webcam.</p>';
  renderLectureFaces();
  window.renderVideoAttendance?.(item);
  window.renderLectureCompletion?.(item);
  $("lecture-log").innerHTML = item.audit.slice().reverse().map(entry => `<p><strong>${escapeHTML(entry.action.replaceAll('_',' '))}</strong> · ${escapeHTML(formatTime(entry.created_utc))}${entry.roll_number ? ' · Roll '+escapeHTML(entry.roll_number) : ''}${entry.face_id ? ' · Face '+entry.face_id : ''}${entry.reason ? '<br>'+escapeHTML(entry.reason):''}</p>`).join('') || '<p>No corrections yet.</p>';
}
function renderLectureFaces() {
  const item = viewedLecture, capture = item?.captures.find(row => row.id===selectedCaptureId);
  if (!capture) { $("lecture-face-review").innerHTML=''; return; }
  const final = item.state==='finalized';
  const options = item.attendance.map(row => `<option value="assign:${escapeHTML(row.roll_number)}">${escapeHTML(row.roll_number)} · ${escapeHTML(row.name)}</option>`).join('');
  $("lecture-face-review").innerHTML = `<img class="lecture-evidence-image" alt="Selected capture with reviewed face labels" src="/api/lectures/${item.id}/captures/${capture.id}/image?v=${item.revision}"><div class="lecture-face-grid">` + capture.detections.map(face => {
    const resolution = item.face_resolutions[`${capture.id}:${face.face_id}`];
    const pending = !resolution && face.decision!=='Matched';
    const label = resolution ? (resolution.action==='ignore' ? 'Ignored · reviewed' : `Assigned · Roll ${resolution.roll_number}`) : face.decision==='Matched' ? `Matched · ${face.candidate_name}` : `${face.decision} · needs review`;
    return `<article class="lecture-face" data-lecture-face="${face.face_id}"><img src="/api/lectures/${item.id}/captures/${capture.id}/faces/${face.face_id}" alt="Face ${face.face_id}"><div><h3>Face ${face.face_id}</h3><span class="status-pill ${pending?'Review':'Present'}">${escapeHTML(label)}</span><p>Original candidate: ${escapeHTML(face.candidate_name || 'None')} ${face.candidate_roll ? '· Roll '+escapeHTML(face.candidate_roll):''}</p><small>Cosine distance: ${face.cosine_distance?.toFixed(4) ?? '—'} · ${escapeHTML(face.reason)}</small>${final ? (resolution ? `<p>${escapeHTML(resolution.reason)}</p>`:'') : `<label>Decision<select data-face-action aria-label="Decision for face ${face.face_id}"><option value="auto">Use automatic decision</option><option value="ignore">Ignore this face (not in roster / unusable)</option>${options}</select></label><input data-face-reason maxlength="500" aria-label="Reason for face ${face.face_id}" placeholder="Reason for decision" value="${escapeHTML(resolution?.reason || '')}"><button data-save-face class="button secondary">Save face decision</button>`}</div></article>`;
  }).join('')+'</div>';
  if (!final) $("lecture-face-review").querySelectorAll('[data-lecture-face]').forEach(card => {
    const resolution = item.face_resolutions[`${capture.id}:${card.dataset.lectureFace}`];
    card.querySelector('[data-face-action]').value = resolution ? resolution.action==='assign' ? `assign:${resolution.roll_number}` : 'ignore' : 'auto';
  });
}
async function lectureMutation(action,payload) {
  if (busy || !viewedLecture) return;
  busy=true; updateControls();
  try {
    const updated=await api(`/api/lectures/${viewedLecture.id}/${action}`,{...payload,revision:viewedLecture.revision});
    viewedLecture=updated;
    if (captureLecture?.id===updated.id) { captureLecture=updated.state==='finalized' ? null : updated; renderAcademicControls(); }
    renderLecture();
    await refreshAfterSave(action==='finalize' ? 'Lecture finalized. Attendance is ready to download.' : 'Lecture updated.');
    return true;
  } catch(error) { toast(error.message,true); return false; }
  finally { busy=false; updateControls(); }
}
$("register-no-photo").addEventListener("click", async () => {
  if (busy || $("add-reference").checked || !$("register-form").reportValidity()) return;
  busy = true;
  updateControls();
  try {
    const student = await api("/api/register/roster", {
      roll_number: $("register-roll").value.trim(),
      name: $("register-name").value.trim(),
      class_id: $("register-class").value,
    });
    $("register-dialog").close();
    await refreshAfterSave(student.name + " enrolled for camera-free check-in.");
  } catch (error) {
    registrationMessage(error.message, true);
  } finally {
    busy = false;
    updateControls();
  }
});

$("roll-call-search").addEventListener("input", () => {
  const query = $("roll-call-search").value.trim().toLowerCase();
  const matches = query && viewedLecture ? viewedLecture.attendance.filter(row =>
    row.name.toLowerCase().includes(query) || row.roll_number === query) : [];
  $("roll-call-results").innerHTML = matches.map(row =>
    '<div class="attendance-row"><strong>' + escapeHTML(row.name) + ' · Roll ' +
    escapeHTML(row.roll_number) + '</strong>' + (row.status === "Present" ?
    '<span class="status-pill Present">Already present</span>' :
    '<button class="button secondary" data-check-in="' + escapeHTML(row.roll_number) +
    '">Mark present</button>') + '</div>').join("");
  if (query && !matches.length) $("roll-call-results").textContent = "No matching student in this lecture.";
});
$("roll-call-results").addEventListener("click", async event => {
  const button = event.target.closest("[data-check-in]");
  if (!button || busy || viewedLecture?.state !== "draft") return;
  const roll = button.dataset.checkIn;
  if (await lectureMutation("attendance", {roll_number: roll, status: "Present",
    reason: "Teacher confirmed presence by roll call."})) {
    toast("Roll " + roll + " marked present.");
    $("roll-call-search").focus();
  }
});

function renderCaptureLecture() {
  $("lecture-capture-banner").hidden=!captureLecture;
  if (captureLecture) {
    $("lecture-capture-label").textContent=captureLecture.title;
    $("attendance-class").innerHTML=`<option>${escapeHTML(captureLecture.context.class_name)}</option>`;
    $("attendance-subject").innerHTML=`<option>${escapeHTML(captureLecture.context.subject_name)}</option>`;
    $("context-note").textContent=`Lecture roster · ${captureLecture.summary.students} students`;
    $("registered-count").textContent=captureLecture.summary.students;
    $("registered-label").textContent='Students in this lecture';
  }
  window.updateSessionStudio?.();
}
function leaveCaptureLecture() {
  if(busy) return;
  captureLecture=null;
  result=null; $("results-panel").hidden=true;
  renderAcademicControls();
}
$("new-lecture").addEventListener('click',newLecture);
$("start-context-lecture").addEventListener('click',newLecture);
$("lecture-close").addEventListener('click',()=>$("lecture-dialog").close());
$("lecture-new-class").addEventListener('change',lectureSubjects);
$("lecture-form").addEventListener('submit',async event=>{
  event.preventDefault(); if(busy)return;
  busy=true;updateControls();
  $("lecture-create").disabled=true;
  try {
    viewedLecture=await api('/api/lectures/create',{title:$("lecture-new-title").value,class_id:$("lecture-new-class").value,subject_id:$("lecture-new-subject").value,lecture_date:$("lecture-new-date").value,lecture_time:$("lecture-new-time").value,timezone:Intl.DateTimeFormat().resolvedOptions().timeZone});
    selectedCaptureId=null;
    $("lecture-dialog").close();renderLecture();navigate('lectures');
    await refreshAfterSave('Lecture started. Add your first capture.');
  }catch(error){$("lecture-message").textContent=error.message;}
  finally{busy=false;$("lecture-create").disabled=false;updateControls();}
});
$("lecture-list").addEventListener('click',event=>{const button=event.target.closest('[data-open-lecture]');if(button)openLecture(button.dataset.openLecture);});
$("lectures-back").addEventListener('click',()=>{if(busy)return;viewedLecture=null;$("lecture-list").hidden=false;$("lecture-workspace").hidden=true;$("new-lecture").hidden=false;});
$("lecture-reload").addEventListener('click',()=>openLecture(viewedLecture.id));
$("lecture-add").addEventListener('click',()=>{
  if(busy || viewedLecture?.state!=='draft')return;
  captureLecture=viewedLecture;
  result=null;$("results-panel").hidden=true;
  navigate('attendance');renderCaptureLecture();updateControls();
});
$("lecture-view").addEventListener('click',()=>openLecture(captureLecture.id));
$("lecture-leave").addEventListener('click',leaveCaptureLecture);
$("lecture-rows").addEventListener('click',event=>{
  if(!event.target.closest('[data-save-row]'))return;
  const row=event.target.closest('[data-lecture-roll]');
  lectureMutation('attendance',{roll_number:row.dataset.lectureRoll,status:row.querySelector('[data-row-status]').value,reason:row.querySelector('[data-row-reason]').value});
});
$("lecture-captures").addEventListener('click',event=>{
  const button=event.target.closest('[data-select-capture]');if(!button||busy)return;
  selectedCaptureId=button.dataset.selectCapture;renderLecture();
});
$("lecture-face-review").addEventListener('click',event=>{
  if(!event.target.closest('[data-save-face]'))return;
  const card=event.target.closest('[data-lecture-face]'), value=card.querySelector('[data-face-action]').value;
  lectureMutation('face',{capture_id:selectedCaptureId,face_id:Number(card.dataset.lectureFace),action:value.startsWith('assign:')?'assign':value,roll_number:value.startsWith('assign:')?value.slice(7):undefined,reason:card.querySelector('[data-face-reason]').value});
});
$("lecture-finalize").addEventListener('click',()=>{
  if(busy||!viewedLecture?.can_finalize)return;
  $("finalize-summary").textContent=`${viewedLecture.title}: ${viewedLecture.summary.present} present, ${viewedLecture.summary.absent} absent, across ${viewedLecture.summary.captures} captures.`;
  $("finalize-confirm").checked=false;$("finalize-submit").disabled=true;$("finalize-message").textContent='';$("finalize-dialog").showModal();
});
$("finalize-close").addEventListener('click',()=>$("finalize-dialog").close());
$("finalize-confirm").addEventListener('change',()=>{$("finalize-submit").disabled=busy||!$("finalize-confirm").checked;});
$("finalize-submit").addEventListener('click',async()=>{
  if(!$("finalize-confirm").checked)return;
  if(await lectureMutation('finalize',{confirm:true}))$("finalize-dialog").close();
});

function renderFaceOverlays() {
  if (!result) return;
  const image = $("result-image");
  if (!image.naturalWidth || !image.naturalHeight) return;
  $("face-overlays").setAttribute("viewBox", `0 0 ${image.naturalWidth} ${image.naturalHeight}`);
  $("face-overlays").innerHTML = result.detections.map(face =>
    `<rect x="${face.x}" y="${face.y}" width="${face.w}" height="${face.h}" rx="3" class="face-hit ${face.face_id === selectedResultFace ? 'selected' : ''}" data-result-face="${face.face_id}" role="button" tabindex="0" aria-pressed="${face.face_id === selectedResultFace}" aria-label="Face ${face.face_id}: ${escapeHTML(face.candidate_name || face.decision)}"><title>Face ${face.face_id} · ${escapeHTML(face.decision)}</title></rect>`).join("");
}
function renderFaceButtons() {
  if (!result) return;
  $("face-buttons").innerHTML = result.detections.map(face => `<button class="face-button ${face.decision}" data-result-face="${face.face_id}" aria-pressed="${face.face_id === selectedResultFace}">Face ${face.face_id}${face.reviewed ? ' · reviewed' : face.decision === 'Matched' ? '' : ' · '+face.decision}</button>`).join("");
}
function selectResultFace(id) {
  if (!result || busy) return;
  const face = result.detections.find(row => row.face_id === id);
  if (!face) return;
  selectedResultFace = id;
  $("roster-filter").value = "All";
  renderAttendance();
  renderFaceOverlays();
  renderFaceButtons();
  $("selected-face-panel").hidden = false;
  $("selected-face-title").textContent = `Face ${id} · ${face.reviewed ? 'Teacher reviewed' : face.decision}`;
  $("selected-face-description").textContent = face.candidate_name
    ? `${face.decision === 'Matched' ? 'Identity' : 'Suggested identity'}: ${face.candidate_name} · Roll ${face.candidate_roll}`
    : 'No identity suggestion available.';
  $("selected-face-reason").textContent = face.reason;
  $("selected-face-message").textContent = '';
  $("selected-face-note").value = '';
  const lecture = result.lecture_capture;
  const editable = lecture && viewedLecture?.id === lecture.lecture_id && viewedLecture.state === 'draft';
  $("selected-face-editor").hidden = !editable;
  $("selected-face-guidance").textContent = editable ? 'Confirm the suggestion, choose a different student, or ignore this face. Enter a reason for the decision.'
    : lecture ? 'Open this lecture to review its saved face decisions.' : 'Create a lecture and add this photo to record identity corrections.';
  if (editable) {
    $("selected-face-student").innerHTML = '<option value="">Choose a student</option>' + viewedLecture.attendance.map(row => `<option value="${escapeHTML(row.roll_number)}">${escapeHTML(row.roll_number)} · ${escapeHTML(row.name)}</option>`).join('');
    $("selected-face-student").value = face.candidate_roll;
  }
  const row = Array.from($("attendance-list").querySelectorAll('[data-result-roll]')).find(row => row.dataset.resultRoll === face.candidate_roll);
  row?.scrollIntoView({behavior:'smooth',block:'nearest'});
  $("selected-face-panel").scrollIntoView({behavior:'smooth',block:'nearest'});
}
async function saveSelectedFace(action) {
  if (busy || !result?.lecture_capture || !selectedResultFace) return;
  const lecture = result.lecture_capture;
  if (viewedLecture?.id !== lecture.lecture_id || viewedLecture.state !== 'draft') return;
  const selected = selectedResultFace;
  const reason = $("selected-face-note").value.trim();
  if (!reason) { $("selected-face-message").textContent = 'Enter a reason for this decision.'; return; }
  const saved = await lectureMutation('face', {capture_id:lecture.capture_id,face_id:selected,
    action,roll_number:$("selected-face-student").value,reason});
  if (!saved) return;
  const capture = viewedLecture.captures.find(row => row.id === lecture.capture_id);
  const detections = capture.detections.map(face => {
    const resolution = viewedLecture.face_resolutions[`${capture.id}:${face.face_id}`];
    if (!resolution) return face;
    const student = viewedLecture.attendance.find(row => row.roll_number === resolution.roll_number);
    return {...face, reviewed:true, decision:student ? 'Matched' : 'Unknown',
      candidate_roll:student?.roll_number || '',candidate_name:student?.name || '', reason:resolution.reason};
  });
  const attendance = viewedLecture.attendance;
  const counts = status => attendance.filter(row => row.status === status).length;
  renderResult({...result, detections,attendance,
    image:`/api/lectures/${lecture.lecture_id}/captures/${lecture.capture_id}/image?v=${viewedLecture.revision}`,
    summary:{...result.summary,present:counts('Present'),absent:counts('Absent'),unconfirmed:counts('Unconfirmed'),review:counts('Review'),
      review_faces:detections.filter(row => row.decision === 'Review').length,
      unknown_faces:detections.filter(row => row.decision === 'Unknown' && !row.reviewed).length}});
  selectResultFace(selected);
}
$("result-image").addEventListener('load',renderFaceOverlays);
for (const id of ['face-overlays','face-buttons']) {
  $(id).addEventListener('click',event => {
    const hit = event.target.closest('[data-result-face]');
    if (hit) selectResultFace(Number(hit.dataset.resultFace));
  });
}
$("face-overlays").addEventListener('keydown',event => {
  if (!['Enter',' '].includes(event.key)) return;
  const hit = event.target.closest('[data-result-face]');
  if (hit) { event.preventDefault(); selectResultFace(Number(hit.dataset.resultFace)); }
});
$("attendance-list").addEventListener('click',event => {
  const row = event.target.closest('[data-result-roll]');
  if (!row || !result) return;
  const face = result.detections.find(face => face.candidate_roll === row.dataset.resultRoll);
  if (face) selectResultFace(face.face_id);
});
$("result-stats").addEventListener('click',event => {
  const button = event.target.closest('[data-roster-status]');
  if (!button || busy) return;
  if (button.dataset.rosterStatus === 'Unknown') {
    const face = result.detections.find(row => row.decision === 'Unknown' && !row.reviewed);
    if (face) selectResultFace(face.face_id);
  } else { $("roster-filter").value = button.dataset.rosterStatus; renderAttendance(); }
});
$("selected-face-confirm").addEventListener('click',() => saveSelectedFace('assign'));
$("selected-face-ignore").addEventListener('click',() => saveSelectedFace('ignore'));
$("selected-face-reset").addEventListener('click',() => saveSelectedFace('auto'));
function updateAdvancedStatus() {
  const enabled = [$("extra-detection").checked ? 'Lighting pass' : '', $("eye-search").checked ? 'Eye search' : ''].filter(Boolean);
  $("advanced-status").textContent = enabled.length ? '· ' + enabled.join(' + ') : '';
}
$("extra-detection").addEventListener('change',updateAdvancedStatus);
$("eye-search").addEventListener('change',updateAdvancedStatus);

renderCameraList();
refreshState().catch((error) => toast(error.message, true));
