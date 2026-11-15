import fs from 'node:fs/promises';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const source = await fs.readFile(new URL('../web/session-studio.js',import.meta.url),'utf8');
function fixture() {
  return {id:'lecture-one',revision:1,state:'draft',title:'AI · Morning lecture',lecture_date:'2026-11-14',context:{class_name:'Computer Science',subject_name:'Artificial Intelligence'},summary:{students:3,present:0,review:0,absent:3,captures:0,video_frames:0,pending_faces:0,video_pending:0},attendance:[{roll_number:'1',name:'Alice',status:'Absent'},{roll_number:'2',name:'Bob',status:'Absent'},{roll_number:'3',name:'Carol',status:'Absent'}],captures:[],video_scans:[],audit:[],face_resolutions:{},can_finalize:false};
}
function setup(item=null) {
  let milliseconds=100000,tick;
  class TestDate extends Date { static now(){return milliseconds;} }
  const nodes=new Map();
  const node=id=>{if(!nodes.has(id))nodes.set(id,{id,hidden:false,disabled:false,attributes:{},dataset:{},classes:new Set(),textContent:'',innerHTML:'',clicks:0,
    classList:{toggle(name,on){const n=node(id);if(on)n.classes.add(name);else n.classes.delete(name);}},
    setAttribute(name,value){this.attributes[name]=value;},getAttribute(name){return this.attributes[name]??null;},removeAttribute(name){delete this.attributes[name];},
    addEventListener(name,fn){this[name]=fn;},click(){this.clicks++;}
  });return nodes.get(id);};
  const steps=['start','capture','review','finish'].map(value=>{const n=node(value);n.dataset.studioStep=value;return n;});
  const context=vm.createContext({Date:TestDate,document:{hidden:false,querySelectorAll:()=>steps,addEventListener(){}},window:{},$:node,
    captureLecture:item,cameraStream:null,selectedImage:null,source:'upload',busy:false,escapeHTML:value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'),formatTime:value=>value,
    setInterval(fn){tick=fn;}});
  vm.runInContext(source,context);
  return {context,node,tick:()=>tick(),advance:value=>{milliseconds+=value;},update:()=>context.window.updateSessionStudio()};
}
{
  const app=setup();assert.equal(app.node('session-companion').hidden,true);assert.equal(app.node('attendance-context').hidden,false);
  app.context.captureLecture=fixture();app.update();
  assert.equal(app.node('session-companion').hidden,false);assert.equal(app.node('attendance-overview').hidden,true);
  assert.equal(app.node('session-next-action').textContent,'Choose class photo');assert.equal(app.node('session-progress').value,0);
}
{
  const item=fixture();item.revision=2;item.summary={...item.summary,review:1,absent:2,video_frames:3,video_pending:1};item.attendance[0].status='Review';
  item.video_scans=[{state:'stopped',started_utc:'2026-11-14T10:00:00Z',tracks:[{proposed_roll:'1',decision:'pending',evidence:[{created_utc:'2026-11-14T10:01:00Z'}]}]}];
  const app=setup(item);
  assert.equal(app.node('session-present').textContent,'0');assert.match(app.node('session-activity').innerHTML,/Video proposal · needs review/);assert.doesNotMatch(app.node('session-activity').innerHTML,/Confirmed present/);
  assert.equal(app.node('review').getAttribute('aria-current'),'step');
  item.video_scans[0].tracks[0].decision='accepted';item.video_scans[0].tracks[0].reviewed_utc='2026-11-14T10:02:00Z';item.summary.present=1;item.summary.review=0;item.attendance[0].status='Present';item.revision++;app.update();
  assert.equal(app.node('session-progress').value,1);assert.equal(app.node('session-percent').textContent,'33% of your class');assert.match(app.node('session-activity').innerHTML,/Confirmed present · video/);
}
{
  const item=fixture();item.summary.captures=1;item.attendance[0].status='Present';item.summary.present=1;item.summary.absent=2;
  item.captures=[{id:'photo',created_utc:'2026-11-14T10:00:00Z',detections:[{face_id:1,decision:'Matched',candidate_roll:'1'}]}];
  item.face_resolutions={'photo:1':{action:'ignore'}};
  const app=setup(item);assert.doesNotMatch(app.node('session-activity').innerHTML,/Alice/);assert.match(app.node('session-activity').innerHTML,/Class photo saved/);
}
{
  const app=setup(fixture());app.advance(5000);app.tick();assert.equal(app.node('session-elapsed').textContent,'00:05');
  app.context.document.hidden=true;app.tick();app.advance(60000);app.tick();assert.equal(app.node('session-elapsed').textContent,'00:05');
  app.context.document.hidden=false;app.tick();app.advance(3000);app.tick();assert.equal(app.node('session-elapsed').textContent,'00:08');
}
{
  const app=setup(fixture());const click=()=>app.node('session-next-action').click.call(app.node('session-next-action'));
  // Our test node's click method is replaced with the real event callback by addEventListener.
  click();assert.equal(app.node('upload-area').clicks,1);
  app.context.busy=true;app.update();click();assert.equal(app.node('upload-area').clicks,1);
}
{
  const app=setup(),item=fixture();item.state='finalized';item.finalized_utc='2026-11-14T10:30:00Z';item.summary.present=2;item.summary.absent=1;
  app.context.window.renderLectureCompletion(item);
  assert.equal(app.node('lecture-completion').hidden,false);assert.equal(app.node('completion-download').href,'/api/lectures/lecture-one/attendance.csv');assert.match(app.node('completion-counts').innerHTML,/<strong>2<\/strong> present/);
  app.context.window.renderLectureCompletion(fixture());assert.equal(app.node('lecture-completion').hidden,true);
}
console.log('PASS: 6 session studio checks (empty state, proposal distinction, ignored faces, paused timer, guarded action, completion).');
