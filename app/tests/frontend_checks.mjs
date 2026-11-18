import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';

const source = await fs.readFile(new URL('../web/app.js', import.meta.url), 'utf8');
const evaluationSource = await fs.readFile(new URL('../web/evaluation.js', import.meta.url), 'utf8');
const response = (status, data) => ({status, ok: status >= 200 && status < 300, json: async () => data});
class TestDOMException extends Error { constructor(message, name) { super(message); this.name = name; } }
const fixture = {xsrf:'token', students:[], history:[], sample_available:true, settings:{cosine_distance_threshold:.3,minimum_gap:.05}};
const deferred = () => { let resolve,reject; const promise = new Promise((r,j) => { resolve = r;reject=j; }); return {promise,resolve,reject}; };
function setup() {
  const nodes = new Map();
  function element(id) {
    if (nodes.has(id)) return nodes.get(id);
    const node = {id, value:'', textContent:'', innerHTML:'', hidden:false, open:false, disabled:false,
      videoWidth:640, videoHeight:480, readyState:2, srcObject:null, listeners:{}, dataset:{},
      classList:{toggle(){},add(){},remove(){}},
      addEventListener(name, fn){(this.listeners[name] ??= []).push(fn);},
      setAttribute(){}, querySelector(selector){return element(`${id}:${selector}`);}, querySelectorAll(){return [];},
      replaceChildren(){}, scrollIntoView(){}, play:async()=>{}, getContext(){return {drawImage(){}};},
      toDataURL(){return 'data:image/jpeg;base64,aGVsbG8=';},
      reset(){}, showModal(){this.open=true;}, close(){this.open=false; for(const fn of this.listeners.close ?? []) fn();}
    };
    nodes.set(id,node); return node;
  }
  const context = vm.createContext({console, Promise, Error, DOMException:TestDOMException, Date, Number, String, Boolean, JSON, File:class {},
    document:{hidden:false,getElementById:element,querySelectorAll(){return [];},addEventListener(){},createElement:()=>element('canvas')},
    window:{addEventListener(){},scrollTo(){}}, navigator:{mediaDevices:{}},
    setTimeout(fn, ms){if(ms===500)queueMicrotask(fn);return 1;},clearTimeout(){},
    fetch:async()=>response(200,fixture)});
  // Suppress only startup I/O; all event handlers and application functions are real.
  vm.runInContext(source.replace('refreshState().catch((error) => toast(error.message, true));',''),context);
  return {context, element, run:code=>vm.runInContext(code,context)};
}

{
  const app=setup(), calls=[];
  app.context.fetch=async(path, options)=>{
    calls.push([path,options]);
    if(path==='/api/session')return response(200,{xsrf:'fresh'});
    return calls.length===1?response(403,{error:'Forbidden'}):response(200,{saved:true});
  };
  await app.run("api('/api/register', {name:'test'})");
  assert.equal(calls.length,3);
  assert.equal(calls[2][1].headers['X-XSRFToken'],'fresh');
}
{
  const app=setup();let attempts=0;
  app.context.fetch=async()=>++attempts<3?response(409,{error:'Busy'}):response(200,fixture);
  await app.run('refreshState()');
  assert.equal(attempts,3);
}
{
  const app=setup();
  app.context.fetch=async()=>{throw new Error('offline');};
  await app.run("refreshAfterSave('Student saved successfully.')");
  assert.match(app.element('toast').textContent,/saved successfully/);
  assert.match(app.element('toast').textContent,/Refresh workspace/);
}
{
  const app=setup(), media=deferred();let stopped=0;
  app.context.navigator.mediaDevices.getUserMedia=()=>media.promise;
  const pending=app.run("openCamera(document.getElementById('camera-video'), () => cameraGeneration === 0)");
  app.run('cameraGeneration++');
  media.resolve({getTracks:()=>[{stop(){stopped++;}}]});
  await assert.rejects(pending,{name:'AbortError'});
  assert.equal(stopped,1);
  assert.equal(app.element('camera-video').srcObject,null);
}
{
  const app=setup(), request=deferred();
  app.run("registrationImage='old-photo'; document.getElementById('register-dialog').open=true");
  app.context.fetch=()=>request.promise;
  const pending=app.element('detect-register').listeners.click[0]();
  app.element('register-dialog').close();
  request.resolve(response(200,{preview_id:'stale',faces:[{index:0,image:'face'}]}));
  await pending;
  assert.equal(app.run('registrationPreview'),null);
  assert.equal(app.element('face-selection').hidden,true);
  assert.equal(app.element('save-student').disabled,true);
}
{
  const app=setup();let saves=0;
  app.run("registrationPreview={preview_id:'ready'}; selectedFace=0; document.getElementById('register-dialog').open=true");
  app.element('register-roll').value='999';app.element('register-name').value='Test';
  app.context.fetch=async(path)=>{
    if(path==='/api/register'){saves++;return response(200,{name:'Test',roll_number:'999'});}
    throw new Error('refresh failed');
  };
  await app.element('register-form').listeners.submit[0]({preventDefault(){}});
  assert.equal(saves,1);
  assert.equal(app.element('register-dialog').open,false);
  assert.match(app.element('toast').textContent,/registered successfully/);
  assert.equal(app.element('save-student').disabled,true);
}
{
  const app=setup();
  app.element('camera-video').srcObject=cameraTrack().stream;
  app.run("source='camera'; live=true; liveGeneration=3");
  app.context.fetch=async()=>response(422,{error:'No face was found.',code:'face_not_found'});
  await app.run('recognize(false,3)');
  assert.equal(app.run('live'),true);
  assert.equal(app.run('waitingForFace'),true);
  assert.equal(app.run('busy'),false);
}
{
  const app=setup();
  app.context.fetch=async()=>{throw new Error('Failed to fetch');};
  await assert.rejects(app.run("api('/api/state')"),/Refresh workspace/);
  assert.equal(app.element('connection-status').textContent,'Disconnected');
}
{
  const app=setup(); let submitted;
  app.run("activeProfile={roll_number:'1',name:'Alice',revision:'old'};document.getElementById('profile-dialog').open=true");
  for(const field of ['roll','name','department','course','semester','section','email','phone','notes'])app.element('profile-'+field).value='';
  app.element('profile-roll').value='101';app.element('profile-name').value='Alice Updated';app.element('profile-course').value='AI';
  app.context.fetch=async(path,options)=>{
    if(path.endsWith('/update')) {submitted={path,payload:JSON.parse(options.body)};return response(200,{roll_number:'101',name:'Alice Updated',course:'AI',revision:'new',photos:[],references:1});}
    return response(200,fixture);
  };
  await app.element('profile-form').listeners.submit[0]({preventDefault(){}});
  assert.equal(submitted.path,'/api/students/1/update');
  assert.equal(submitted.payload.roll_number,'101');
  assert.equal(submitted.payload.revision,'old');
  assert.equal(app.run('activeProfile.roll_number'),'101');
  assert.equal(app.run('profileDirty'),false);
}
{
  const app=setup();let posts=0;
  app.run("activeProfile={roll_number:'1',name:'Alice',revision:''};document.getElementById('profile-dialog').open=true");
  app.context.fetch=async()=>{posts++;return response(200,{});};
  app.element('delete-roll').value='2';
  await app.element('confirm-delete-student').listeners.click[0]();
  assert.equal(posts,0);
  assert.equal(app.element('profile-dialog').open,true);
}
{
  const app=setup();
  app.run("activeProfile={roll_number:'1',name:'Alice'};profileDirty=true;document.getElementById('profile-dialog').open=true");
  app.element('profile-add-photo').listeners.click[0]();
  assert.equal(app.element('profile-dialog').open,true);
  assert.match(app.element('profile-message').textContent,/Save your changes/);
}
{
  const app=setup();
  app.run("registrationPreview={preview_id:'photo1'};selectedFace=0;registrationQueue=['photo2'];registrationImage='photo1';document.getElementById('register-dialog').open=true");
  app.element('register-roll').value='1';app.element('register-name').value='Alice';app.element('add-reference').checked=true;
  app.context.fetch=async(path)=>path==='/api/register'?response(200,{roll_number:'1',name:'Alice'}):response(200,fixture);
  await app.element('register-form').listeners.submit[0]({preventDefault(){}});
  assert.equal(app.element('register-dialog').open,true);
  assert.equal(app.run('registrationImage'),'photo2');
  assert.equal(app.run('selectedFace'),null);
  assert.equal(app.element('save-student').disabled,true);
}

const groupId='a'.repeat(32), subjectId='b'.repeat(32);
const academicFixture={...fixture,students:[{roll_number:'1',name:'Alice',registered:true,references:1},{roll_number:'2',name:'Bob',registered:true,references:1}],academics:{revision:'rev1',classes:[{id:groupId,name:'AI A',student_rolls:['1']}],subjects:[{id:subjectId,class_id:groupId,name:'Deep Learning',code:'AI501',teacher:''}]}};
{
  const app=setup();app.context.initialData=academicFixture;
  app.run('state=initialData; renderAcademicControls(); result={old:true};live=true');
  app.element('attendance-class').value=groupId;
  app.element('attendance-subject').value='';
  app.element('attendance-class').listeners.change[0]();
  assert.equal(app.run('selectedSubjectId'),subjectId);
  assert.equal(app.run('live'),false);
  assert.equal(app.run('result'),null);
  assert.equal(app.element('registered-count').textContent,1);
}
{
  const app=setup();let submitted;
  app.context.initialData=academicFixture;
  app.run('state=initialData;openClassEditor()');
  app.element('class-name').value='AI B';
  app.run("enrollment=new Set(['1','2'])");
  app.context.fetch=async(path, options)=>{
    if(path==='/api/classes/save') {submitted=JSON.parse(options.body);return response(200,{class:{id:'c'.repeat(32),name:'AI B'},academics:academicFixture.academics});}
    return response(200,academicFixture);
  };
  await app.element('class-form').listeners.submit[0]({preventDefault(){}});
  assert.equal(submitted.revision,'rev1');
  assert.equal(submitted.student_rolls.sort().join(','),'1,2');
  assert.equal(app.element('class-dialog').open,false);
}
{
  const app=setup();let submitted;
  app.context.initialData=academicFixture;
  app.run('state=initialData');app.context.groupId=groupId;
  app.run('openSubjectEditor(groupId)');
  app.element('subject-name').value='Computer Vision';app.element('subject-code').value='CV101';
  app.context.fetch=async(path,options)=>{
    if(path==='/api/subjects/save'){submitted=JSON.parse(options.body);return response(200,{subject:{class_id:groupId,name:'Computer Vision'},academics:academicFixture.academics});}
    return response(200,academicFixture);
  };
  await app.element('subject-form').listeners.submit[0]({preventDefault(){}});
  assert.equal(submitted.class_id,groupId);assert.equal(submitted.code,'CV101');assert.equal(submitted.revision,'rev1');
}
{
  const app=setup();app.context.initialData={...academicFixture,history:[{run_id:'1',class_id:groupId,subject_id:subjectId,class_name:'AI A',subject_name:'Deep Learning',created_utc:'2026-11-11T12:00:00Z',present:1,faces:1,source:'upload'},{run_id:'2',class_id:'other',subject_id:'other',class_name:'Excluded Class',created_utc:'2026-11-11T12:00:00Z',present:2,faces:2,source:'upload'}]};
  app.run('state=initialData');app.element('history-class-filter').value=groupId;app.element('history-subject-filter').value=subjectId;
  app.run('renderHistory()');
  assert.match(app.element('history-list').innerHTML,/Deep Learning/);assert.doesNotMatch(app.element('history-list').innerHTML,/Excluded Class/);
}
{
  const app=setup();app.context.initialData=academicFixture;app.run("state=initialData;enrollment=new Set(['2'])");
  app.element('enrollment-search').value='Alice';app.element('enroll-shown').listeners.click[0]();
  assert.equal(app.run("Array.from(enrollment).sort().join(',')"),'1,2');
}
{
  const app=setup();let submitted;
  app.context.groupId=groupId;app.context.subjectId=subjectId;
  app.run("selectedImage='test-image';selectedClassId=groupId;selectedSubjectId=subjectId");
  app.context.fetch=async(path,options)=>{submitted=JSON.parse(options.body);return response(422,{error:'No face',code:'face_not_found'});};
  await app.run('recognize(true)');
  assert.equal(submitted.class_id,groupId);assert.equal(submitted.subject_id,subjectId);
}

{
 const app=setup(), calls=[];
 app.run(`state=${JSON.stringify(fixture)}; captureLecture={id:'abc',revision:7,context:{},summary:{students:2,present:0,captures:0}}; selectedImage='image'; renderLecture=()=>{};renderCaptureLecture=()=>{};renderResult=()=>{};refreshAfterSave=async()=>{};`);
 app.context.fetch=async(path,options)=>{calls.push([path,JSON.parse(options.body)]);return response(200,{lecture:{id:'abc',revision:8},capture_report:{lecture_capture:{capture_id:'cap'},summary:{}}});};
 await app.run('recognize(true)');
 assert.equal(calls[0][0],'/api/lectures/abc/capture');
 assert.equal(calls[0][1].revision,7);
 assert.equal(app.run('captureLecture.revision'),8);
}
{
 const app=setup(),calls=[];
 app.run(`state=${JSON.stringify(fixture)}; viewedLecture={id:'abc',revision:3,can_finalize:true}; renderLecture=()=>{}; refreshAfterSave=async()=>{};`);
 app.context.fetch=async(path,options)=>{calls.push([path,JSON.parse(options.body)]);return response(200,{id:'abc',revision:4,state:'draft',can_finalize:true});};
 await app.run("lectureMutation('attendance',{roll_number:'1',status:'Absent',reason:'Manual check'})");
 assert.equal(calls[0][1].revision,3);
 assert.equal(app.run('viewedLecture.revision'),4);
}
{
 const app=setup();
 app.run("viewedLecture={can_finalize:false};");
 for(const fn of app.element('lecture-finalize').listeners.click) await fn();
 assert.equal(app.element('finalize-dialog').open,false);
 app.run("viewedLecture={can_finalize:true,title:'Lecture',summary:{present:1,absent:2,captures:1}};");
 for(const fn of app.element('lecture-finalize').listeners.click) await fn();
 assert.equal(app.element('finalize-dialog').open,true);
 assert.equal(app.element('finalize-submit').disabled,true);
}

{
 const app=setup();
 app.run(`state={students:[{roll_number:'10',name:'Zara',references:1,registered:true},{roll_number:'2',name:'Alice',references:3,registered:true}],academics:{classes:[{id:'demo',name:'Demo',student_rolls:['2']}],subjects:[]}};`);
 app.element('directory-sort').value='name';
 app.run('renderStudents()');
 assert.ok(app.element('student-grid').innerHTML.indexOf('Alice')<app.element('student-grid').innerHTML.indexOf('Zara'));
 app.element('directory-class').value='demo';
 app.run('renderStudents()');
 assert.ok(!app.element('student-grid').innerHTML.includes('Zara'));
}
{
 const app=setup();
 app.run(`result={detections:[{face_id:1,candidate_roll:'2',candidate_name:'Alice',decision:'Unknown',reason:'Rejected candidate'}],attendance:[{roll_number:'2',name:'Alice',status:'Absent'}]}; selectResultFace(1);`);
 assert.ok(app.element('selected-face-description').textContent.startsWith('Suggested identity'));
 assert.equal(app.element('selected-face-editor').hidden,true);
 assert.ok(app.element('attendance-list').innerHTML.includes('face-selected'));
}
{
 const app=setup();
 app.run(`result={lecture_capture:{lecture_id:'lecture',capture_id:'capture'}}; selectedResultFace=1; viewedLecture={id:'lecture',state:'draft'};`);
 await app.run("saveSelectedFace('assign')");
 assert.equal(app.element('selected-face-message').textContent,'Enter a reason for this decision.');
}

{
 const app=setup();
 app.context.document.querySelector=()=>app.element('evaluation-nav');
 vm.runInContext(evaluationSource,app.context);
 app.element('eval-source').naturalWidth=100;
 app.element('eval-source').naturalHeight=100;
 for(const [id,value] of [['x','0'],['y','0'],['w','60'],['h','60']]) app.element('eval-'+id).value=value;
 for(const fn of app.element('eval-box-add').listeners.click)fn();
 assert.ok(app.element('eval-label-list').innerHTML.includes('Expected identity for box 1'));
 for(const fn of app.element('eval-box-add').listeners.click)fn();
 assert.equal(app.element('eval-draw-message').textContent,'Boxes must not overlap. Remove or redraw the existing box.');
}

function cameraTrack(id='usb') {
 const track={stopped:false,handlers:{},stop(){this.stopped=true;},getSettings(){return {deviceId:id};},addEventListener(name,fn){this.handlers[name]=fn;}};
 const stream={getTracks:()=>[track],getVideoTracks:()=>[track]};return {track,stream};
}
{
 const app=setup();app.context.navigator.mediaDevices.enumerateDevices=async()=>[
  {kind:'videoinput',deviceId:'builtin',label:'Built-in webcam'},
  {kind:'audioinput',deviceId:'mic',label:'Microphone'},
  {kind:'videoinput',deviceId:'usb',label:'USB <camera>'},
  {kind:'videoinput',deviceId:'usb',label:'Duplicate'}];
 await app.run('refreshCameraList()');
 assert.match(app.element('attendance-camera-select').innerHTML,/Built-in webcam/);
 assert.match(app.element('attendance-camera-select').innerHTML,/USB &lt;camera&gt;/);
 assert.doesNotMatch(app.element('attendance-camera-select').innerHTML,/Microphone|Duplicate/);
 assert.equal(app.element('attendance-camera-select').innerHTML,app.element('registration-camera-select').innerHTML);
}
{
 const app=setup(),device=cameraTrack();let request;
 app.context.navigator.mediaDevices.getUserMedia=async constraints=>{request=constraints;return device.stream;};
 app.run("preferredCameraId='usb'");await app.run("openCamera(document.getElementById('camera-video'))");
 assert.equal(request.video.deviceId.exact,'usb');assert.equal(request.audio,false);assert.equal(request.video.facingMode,undefined);
 assert.equal(device.track.stopped,false);
}
{
 const app=setup(),old=cameraTrack('builtin'),next=cameraTrack('usb'),saved=new Map();let calls=0;
 app.context.localStorage={setItem(k,v){saved.set(k,v);}};app.context.oldStream=old.stream;
 app.context.navigator.mediaDevices.getUserMedia=async constraints=>{calls++;assert.equal(old.track.stopped,true);assert.equal(constraints.video.deviceId.exact,'usb');return next.stream;};
 app.run("cameraStream=oldStream; source='camera'; availableCameras=[{deviceId:'usb',label:'USB'}]");
 await app.run("chooseCamera({target:{value:'usb'}})");
 assert.equal(calls,1);assert.equal(app.run('cameraStream'),next.stream);assert.equal(saved.get('classroom-attendance-camera'),'usb');
 assert.equal(app.element('registration-camera-select').value,'usb');
 next.track.handlers.ended();assert.equal(app.run('cameraStream'),null);assert.match(app.element('toast').textContent,/disconnected/);
}
{
 const app=setup(),device=cameraTrack();app.context.navigator.mediaDevices.getUserMedia=async()=>device.stream;
 app.element('register-dialog').open=true;await app.run('startRegistrationCamera()');
 assert.equal(app.element('register-capture').disabled,false);device.track.handlers.ended();
 assert.equal(app.run('registrationStream'),null);assert.equal(app.element('register-capture').disabled,true);
 assert.match(app.element('registration-message').textContent,/disconnected/);
}
{
 const app=setup();app.context.navigator.mediaDevices.enumerateDevices=async()=>[{kind:'videoinput',deviceId:'builtin',label:'Built-in'}];
 app.run("preferredCameraId='missing'");await app.run('refreshCameraList()');
 assert.equal(app.element('attendance-camera-select').value,'missing');assert.match(app.element('attendance-camera-message').textContent,/unavailable/);
 assert.match(app.element('attendance-camera-select').innerHTML,/Saved camera/);
 app.run('live=true');await app.run("chooseCamera({target:{value:'builtin'}})");assert.equal(app.run('preferredCameraId'),'missing');
}
{
 const app=setup();app.context.navigator.mediaDevices.enumerateDevices=async()=>{throw new Error('blocked');};
 await app.run('refreshCameraList()');assert.match(app.element('attendance-camera-message').textContent,/Could not refresh/);
 assert.equal(app.element('attendance-camera-refresh').disabled,false);
}
{
 const app=setup(),old=cameraTrack('usb');app.context.activeStream=old.stream;
 app.context.navigator.mediaDevices.enumerateDevices=async()=>[];
 app.run('cameraAccessGranted=true; cameraStream=activeStream');await app.run('refreshCameraList()');
 assert.equal(old.track.stopped,true);assert.equal(app.run('cameraStream'),null);assert.match(app.element('attendance-camera-message').textContent,/disconnected/);
}

{
 const app=setup(),request=deferred(),late=cameraTrack();
 app.context.navigator.mediaDevices.getUserMedia=()=>request.promise;
 app.run("source='camera'");const starting=app.run('startAttendanceCamera()');
 app.run('stopCamera()');await new Promise(resolve=>setImmediate(resolve));
 assert.equal(app.run('cameraOpening'),false,'Closing a pending permission request must unlock camera controls');
 request.resolve(late.stream);await starting;await new Promise(resolve=>setImmediate(resolve));
 assert.equal(late.track.stopped,true);assert.equal(app.element('camera-video').srcObject,null);
}
{
 const app=setup(),play=deferred(),old=cameraTrack('old'),next=cameraTrack('new');let requests=0;
 app.context.navigator.mediaDevices.getUserMedia=async()=>++requests===1?old.stream:next.stream;
 app.element('camera-video').play=()=>play.promise;app.run("source='camera'");
 const first=app.run('startAttendanceCamera()');await new Promise(resolve=>setImmediate(resolve));
 app.run('stopCamera()');await first;
 assert.equal(old.track.stopped,true,'Stop must release a stream waiting for playback');
 app.element('camera-video').play=async()=>{};await app.run('startAttendanceCamera()');
 play.resolve();await new Promise(resolve=>setImmediate(resolve));
 assert.equal(app.element('camera-video').srcObject,next.stream);assert.equal(next.track.stopped,false);
}
{
 const app=setup(),old=cameraTrack(),play=deferred(),next=cameraTrack('new');
 app.context.navigator.mediaDevices.getUserMedia=async()=>old.stream;app.element('camera-video').play=()=>play.promise;
 const pending=app.run("openCamera(document.getElementById('camera-video'))");
 await new Promise(resolve=>setImmediate(resolve));app.run('stopCamera()');
 await assert.rejects(pending,{name:'AbortError'});
 app.element('camera-video').srcObject=next.stream;play.reject(new Error('Old playback failed'));await new Promise(resolve=>setImmediate(resolve));
 assert.equal(app.element('camera-video').srcObject,next.stream);
}
{
 const app=setup(),request=deferred();let timeout;
 app.context.navigator.mediaDevices.enumerateDevices=()=>request.promise;
 app.context.setTimeout=(fn,ms)=>{if(ms===5000)timeout=fn;return 1;};
 const pending=app.run('refreshCameraList()');assert.equal(typeof timeout,'function');timeout();await pending;
 assert.equal(app.run('cameraListLoading'),false);assert.equal(app.element('attendance-camera-refresh').disabled,false);
 request.resolve([{kind:'videoinput',deviceId:'late',label:'Late camera'}]);await new Promise(resolve=>setImmediate(resolve));
 assert.doesNotMatch(app.element('attendance-camera-select').innerHTML,/Late camera/);
}
{
 const app=setup(),device=cameraTrack();
 assert.throws(()=>app.run("snapshot(document.getElementById('camera-video'))"),/camera.*not ready|camera.*unavailable/i);
 app.element('camera-video').srcObject=device.stream;device.track.readyState='ended';
 assert.throws(()=>app.run("snapshot(document.getElementById('camera-video'))"),/camera.*not ready|camera.*unavailable/i);
 device.track.readyState='live';device.track.muted=true;
 assert.throws(()=>app.run("snapshot(document.getElementById('camera-video'))"),/camera.*not ready|camera.*unavailable/i);
}

{
 const app=setup(),device=cameraTrack(),play=deferred();let timeout;
 app.context.navigator.mediaDevices.getUserMedia=async()=>device.stream;
 app.context.setTimeout=(fn,ms)=>{if(ms===15000)timeout=fn;return 1;};
 app.element('camera-video').play=()=>play.promise;app.run("source='camera'");
 const pending=app.run('startAttendanceCamera()');await new Promise(resolve=>setImmediate(resolve));
 assert.equal(app.element('stop-camera').hidden,false);assert.match(app.element('stop-camera').textContent,/Cancel/);
 timeout();await pending;assert.equal(device.track.stopped,true);assert.equal(app.run('cameraOpening'),false);
 assert.equal(app.element('stop-camera').hidden,true);assert.match(app.element('toast').textContent,/did not become ready/);
 play.resolve();await new Promise(resolve=>setImmediate(resolve));
}
{
 const app=setup();
 app.run("registrationPreview={faces:[{index:0,quality:{status:'retake',checks:[{label:'Lighting',ok:false,tip:'Face a soft light.'}]}}]};selectedFace=0;updateRegistrationGuide()");
 assert.match(app.element('save-student').textContent,/Save despite warnings/);
 assert.match(app.element('registration-quality').innerHTML,/Face a soft light/);
 app.run("clearRegistrationSelection()");
 assert.equal(app.element('registration-quality').hidden,true);
}
{
 const app=setup();let payload;
 app.run("registrationPreview={preview_id:'first',faces:[{index:0,quality:{status:'retake',checks:[]}}]};selectedFace=0;document.getElementById('register-dialog').open=true");
 app.element('register-roll').value='77';app.element('register-name').value='Synthetic';app.element('keep-registering').checked=true;
 app.context.fetch=async(path,options)=>{
   if(path==='/api/register'){payload=JSON.parse(options.body);return response(200,{roll_number:'77',name:'Synthetic',reference_count:1});}
   return response(200,fixture);
 };
 await app.element('register-form').listeners.submit[0]({preventDefault(){}});
 assert.equal(payload.quality_acknowledged,true);
 assert.equal(app.element('register-dialog').open,true);
 assert.equal(app.element('add-reference').checked,true);
 assert.equal(app.element('register-roll').disabled,true);
 assert.equal(app.element('register-name').disabled,true);
 assert.equal(app.element('finish-registration').hidden,false);
 assert.equal(app.run('registrationPreview'),null);
 assert.match(app.element('registration-progress').textContent,/1 reference saved/);
 app.element('finish-registration').listeners.click[0]();assert.equal(app.element('register-dialog').open,false);
}
{
 const app=setup();let requests=[];
 app.run("registrationPreview={preview_id:'first'};selectedFace=0;registrationQueue=['next-photo'];document.getElementById('register-dialog').open=true");
 app.element('register-roll').value='77';app.element('register-name').value='Synthetic';
 app.context.fetch=async(path,options)=>{
  if(path==='/api/register'){requests.push(JSON.parse(options.body));return response(200,{roll_number:'77',name:'Synthetic',reference_count:requests.length});}
  return response(200,fixture);
 };
 await app.element('register-form').listeners.submit[0]({preventDefault(){}});
 app.run("registrationPreview={preview_id:'next'};selectedFace=0");
 await app.element('register-form').listeners.submit[0]({preventDefault(){}});
 assert.equal(requests[0].add_reference,undefined);assert.equal(requests[1].add_reference,true);
 assert.equal(requests[1].class_id,'');
}
{
 const app=setup();app.run("registrationQueue=['next-photo'];registrationImage='bad-photo';registrationPreview={preview_id:'old'};selectedFace=0");
 app.element('skip-register-photo').listeners.click[0]();
 assert.equal(app.run('registrationImage'),'next-photo');assert.equal(app.run('registrationPreview'),null);
 assert.equal(app.element('save-student').disabled,true);
}
{
 const app=setup(),request=deferred();
 app.run("registrationPreview={preview_id:'first'};selectedFace=0;document.getElementById('register-dialog').open=true");
 app.element('register-roll').value='77';app.element('register-name').value='Synthetic';app.context.fetch=path=>path==='/api/register'?request.promise:Promise.resolve(response(200,fixture));
 const pending=app.element('register-form').listeners.submit[0]({preventDefault(){}});
 app.element('register-dialog').close();request.resolve(response(200,{roll_number:'77',name:'Synthetic',reference_count:1}));await pending;
 assert.equal(app.run('registrationIdentity'),null);assert.equal(app.element('register-dialog').open,false);
}
console.log('PASS: 43 frontend checks, including guided enrollment, quality warnings, batch references, camera lifecycle and stale responses.');
