import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
import vm from 'node:vm';
const source=await fs.readFile(new URL('../web/video-attendance.js',import.meta.url),'utf8');
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {resolve,promise};};
function setup() {
  const nodes=new Map(),calls=[],scheduled=[];
  const node=id=>{if(!nodes.has(id))nodes.set(id,{id,hidden:false,disabled:false,listeners:{},append(){},setAttribute(){},querySelectorAll(){return []},addEventListener(event,fn){this.listeners[event]=fn;},videoWidth:1920,videoHeight:1080});return nodes.get(id);};
  const item={id:'lecture',state:'draft',revision:1,summary:{video_frames:0},video_scans:[],attendance:[]};
  const context=vm.createContext({document:{hidden:false,getElementById:node,createElement:()=>({setAttribute(){},getContext:()=>({drawImage(){}}),toDataURL:()=> 'frame'}),addEventListener(){}},
    window:{},$:node,source:'camera',busy:false,live:false,cameraStream:{},captureLecture:item,viewedLecture:null,
    cameraFrameReady:()=>true,renderCaptureLecture(){},renderLecture(){},stopLive(){},toast(){},refreshAfterSave:async()=>{},escapeHTML:s=>s,
    crypto:{randomUUID:()=> 'a'.repeat(32)},setTimeout(fn){scheduled.push(fn);return scheduled.length;},clearTimeout(){},
    api:async(path,payload)=>{calls.push({path,payload});if(path.endsWith('/start'))return {scan_id:'scan',lecture:{...item,revision:2}};if(path.endsWith('/frame'))return {lecture:{...item,revision:3,summary:{video_frames:1}}};if(path.endsWith('/stop'))return {lecture:{...item,revision:4}};return {...item,revision:3};},
    updateControls(){context.window.updateVideoControls?.();}
  });
  vm.runInContext(source,context);
  return {context,node,calls,scheduled,click:()=>node('video-attendance-button').listeners.click()};
}
{
  const app=setup();await app.click();
  assert.equal(app.calls.length,2);assert.ok(app.calls[1].path.endsWith('/frame'));
  assert.equal(app.scheduled.length,1);assert.equal(app.context.busy,false);
  await app.click();assert.ok(app.calls.at(-1).path.endsWith('/stop'));
  assert.equal(app.node('video-attendance-button').textContent,'Start video attendance');
}
{
  const app=setup(),pending=deferred(),original=app.context.api;
  app.context.api=async(path,payload)=>path.endsWith('/frame') ? (app.calls.push({path,payload}),pending.promise) : original(path,payload);
  const running=app.click();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(app.context.busy,true);app.context.window.stopVideoAttendance();
  assert.equal(app.calls.some(call=>call.path.endsWith('/stop')),false);
  pending.resolve({lecture:{...app.context.captureLecture,revision:3,summary:{video_frames:1}}});await running;
  assert.ok(app.calls.at(-1).path.endsWith('/stop'));assert.equal(app.calls.at(-1).payload.revision,3);
}
{
  const app=setup();app.context.captureLecture=null;app.context.updateControls();
  assert.equal(app.node('video-attendance-button').disabled,true);
  await app.click();assert.equal(app.calls.length,0);
}
{
 const app=setup();app.context.cameraFrameReady=()=>false;app.context.updateControls();
 assert.equal(app.node('video-attendance-button').disabled,true);await app.click();assert.equal(app.calls.length,0);
}
console.log('PASS: 4 video interface checks (paced sampling, stop during an in-flight frame, and lecture requirement).');
