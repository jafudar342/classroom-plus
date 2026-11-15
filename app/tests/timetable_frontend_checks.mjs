import fs from 'node:fs/promises';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const source=await fs.readFile(new URL('../web/timetable.js',import.meta.url),'utf8');
const day='2026-11-16',slot='a'.repeat(32);
const entry={id:slot,title:'AI',class_id:'group',class_name:'Class A',subject_id:'subject',subject_name:'AI',weekdays:[0],start_time:'09:00',end_time:'10:00',starts_on:day,ends_on:'',late_after_minutes:10,active:true,available:true};
const schedule={slot_id:slot,date:day,start_time:'09:00',end_time:'10:00',late_after_minutes:10,timezone:'Asia/Kolkata'};
function setup(final=false) {
 const nodes=new Map(),handlers={},calls=[],academics={classes:[{id:'group',name:'Class A'}],subjects:[{id:'subject',class_id:'group',name:'AI'}]};
 let catalog={revision:4,date:day,today:day,timezone:'Asia/Kolkata',entries:[entry],occurrences:[{...entry,schedule,status:'Needs attendance',lecture_id:null,summary:null}],day_summary:{}};
 function node(id){if(!nodes.has(id))nodes.set(id,{id,attrs:{},dataset:{},value:'',hidden:false,disabled:false,checked:false,handlers:{},innerHTML:'',textContent:'',setAttribute(k,v){this.attrs[k]=v;},getAttribute(k){return this.attrs[k]??null;},hasAttribute(k){return Object.hasOwn(this.attrs,k);},addEventListener(k,fn){this.handlers[k]=fn;},querySelectorAll(){return [];},reset(){},focus(){},showModal(){this.open=true;},close(){this.open=false;}});return nodes.get(id);}
 const weekdays=Array.from({length:7},(_,index)=>{const input=node('day'+index);input.value=String(index);return input;});
 node('timetable-edit-class').value='group';node('timetable-edit-subject').value='subject';node('video-attendance-button').attrs['aria-pressed']='false';
 const start=node('start');start.attrs['data-scheduled-start']=slot;start.dataset={scheduledStart:slot,scheduledDate:day};
 const context=vm.createContext({console,document:{hidden:false,getElementById:node,querySelector:selector=>node(selector),querySelectorAll:selector=>selector.includes('timetable-weekday')?(selector.endsWith(':checked')?weekdays.filter(input=>input.checked):weekdays):selector.startsWith('[data-scheduled-start]')?[start]:[],addEventListener(k,fn){handlers[k]=fn;}},window:{},
  busy:false,captureLecture:null,viewedLecture:null,selectedCaptureId:null,selectedClassId:'all-students',selectedSubjectId:'',selectedImage:'previous photo',photoGeneration:0,result:{},
  academicData:()=>academics,escapeHTML:value=>String(value),toast(){},renderCaptureLecture(){},renderAcademicControls(){},renderLecture(){},navigate(page){context.page=page;},setSource(){},refreshAfterSave:async()=>{},setInterval(){},updateControls(){context.window.updateTimetableControls?.();},
  api:async(path,payload)=>{calls.push({path,payload});if(payload&&path==='/api/timetable/start')return {lecture:{id:'lecture',state:final?'finalized':'draft',revision:1,captures:[],context:{class_id:'group',subject_id:'subject'},summary:{},schedule},resumed:false};if(payload)return catalog;return catalog;}
 });
 vm.runInContext(source,context);
 return {context,node,calls,start,handlers,setCatalog:changes=>{catalog={...catalog,...changes};},async settle(){await new Promise(resolve=>setImmediate(resolve));},clickStart(){handlers.click({target:{closest:()=>start}});}};
}
{
 const app=setup();await app.settle();assert.match(app.node('timetable-day-list').innerHTML,/Start attendance/);app.clickStart();await app.settle();
 const request=app.calls.find(call=>call.path==='/api/timetable/start');assert.equal(request.payload.revision,4);assert.equal(request.payload.date,day);
 assert.equal(app.context.captureLecture.id,'lecture');assert.equal(app.context.selectedClassId,'group');assert.equal(app.context.selectedImage,null);assert.equal(app.context.page,'attendance');
}
{
 const app=setup(true);await app.settle();app.clickStart();await app.settle();assert.equal(app.context.viewedLecture.state,'finalized');assert.equal(app.context.page,'lectures');
}
{
 const app=setup();await app.settle();app.context.busy=true;app.context.window.updateTimetableControls();app.clickStart();await app.settle();assert.equal(app.calls.some(call=>call.path==='/api/timetable/start'),false);
}
{
 const app=setup();await app.settle();app.node('timetable-new').handlers.click();app.node('timetable-edit-title').value='Custom title';
 app.setCatalog({revision:5});app.context.window.refreshTimetable();await app.settle();assert.equal(app.node('timetable-edit-title').value,'Custom title');
 await app.node('timetable-form').handlers.submit({preventDefault(){}});const save=app.calls.find(call=>call.path==='/api/timetable'&&call.payload);assert.equal(save.payload.revision,4);assert.equal(save.payload.title,'Custom title');
}
console.log('PASS: 4 timetable interface checks (prefilled start, finalized view, busy guard, frozen editor revision).');
