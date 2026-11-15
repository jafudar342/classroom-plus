import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
const source=await fs.readFile(new URL('../web/settings.js',import.meta.url),'utf8');
const defaults={detector:'retinaface',model:'Facenet512',cosine_distance_threshold:.3,minimum_gap:.05,default_extra_detection:false,default_eye_search:false,live_interval_ms:2500,video_sample_interval_ms:1500,video_required_samples:3,video_min_face_pixels:48,video_min_sharpness:35,default_late_after_minutes:10,default_start_time:'09:00',default_end_time:'10:00',default_directory_view:'grid',attendance_target:75};
function setup(changes={},active=[]) {
 const nodes=new Map(),calls=[],events={};
 let catalog={revision:'r1',values:{...defaults,...changes},defaults,models:{detectors:[{id:'retinaface',name:'RetinaFace'}],embeddings:[{id:'Facenet512',name:'FaceNet512'}]},gallery:{templates:2,dimensions:512,normalization:'base'},active_scans:active};
 const node=id=>{if(!nodes.has(id))nodes.set(id,{id,value:'',checked:false,disabled:false,hidden:false,type:typeof defaults[id.slice(5)]==='boolean'?'checkbox':'text',attrs:{},handlers:{},setAttribute(k,v){this.attrs[k]=v;},getAttribute(k){return this.attrs[k]??null;},addEventListener(k,fn){this.handlers[k]=fn;}});return nodes.get(id);};
 const context=vm.createContext({console,setTimeout,clearTimeout,state:{settings:{...defaults,...changes}},directoryListView:false,busy:false,
  document:{documentElement:{dataset:{theme:'dark'}},getElementById:node,querySelector:selector=>node(selector)},window:{addEventListener(k,fn){events[k]=fn;},setClassroomTheme(theme){context.document.documentElement.dataset.theme=theme;events['classroom-theme-change']?.();}},
  renderStudents(){},updateAdvancedStatus(){},escapeHTML:value=>String(value),openLecture:async()=>{},
  updateControls(){context.window.updateSettingsControls?.();},refreshAfterSave:async()=>{context.state.settings={...catalog.values};context.window.applySettingsDefaults(context.state.settings);},
  api:async(path,payload)=>{calls.push({path,payload});if(payload){if(payload.revision!==catalog.revision)throw new Error('Settings changed in another tab.');catalog={...catalog,revision:'saved',values:{...payload.values}};}return JSON.parse(JSON.stringify(catalog));}
 });
 vm.runInContext(source,context);
 return {context,node,calls,setCatalog:changes=>{catalog={...catalog,...changes};},async settle(){await new Promise(resolve=>setImmediate(resolve));},open(){node('[data-page="settings"]').handlers.click();},input(key,value){node('pref-'+key).value=String(value);node('settings-form').handlers.input();},submit(){return node('settings-form').handlers.submit({preventDefault(){}});}};
}
{
 const app=setup();app.open();await app.settle();assert.equal(app.node('pref-model').value,'Facenet512');assert.equal(app.node('settings-save').disabled,true);
 app.input('cosine_distance_threshold',.2);assert.equal(app.node('settings-save').disabled,false);await app.submit();
 const request=app.calls.find(call=>call.payload);assert.equal(request.payload.values.cosine_distance_threshold,.2);assert.equal(request.payload.values.detector,'retinaface');assert.equal(app.node('settings-draft-label').textContent,'Saved settings');
}
{
 const app=setup({minimum_gap:.2});app.open();await app.settle();app.node('settings-defaults').handlers.click();
 assert.equal(app.node('pref-minimum_gap').value,'0.05');assert.equal(app.calls.filter(call=>call.payload).length,0);assert.equal(app.node('settings-save').disabled,false);
}
{
 const app=setup();app.open();await app.settle();app.input('minimum_gap',.1);app.setCatalog({revision:'other'});app.open();await app.settle();
 assert.equal(app.node('pref-minimum_gap').value,'0.1');await app.submit();assert.match(app.node('settings-message').textContent,/changed in another tab/);
 assert.equal(app.calls.find(call=>call.payload).payload.revision,'r1');
}
{
 const app=setup({},[{id:'lecture',title:'AI'}]);app.open();await app.settle();app.input('minimum_gap',.1);assert.equal(app.node('settings-save').disabled,true);
 app.setCatalog({active_scans:[]});app.open();await app.settle();assert.equal(app.node('pref-minimum_gap').value,'0.1');assert.equal(app.node('settings-save').disabled,false);
}
{
 const app=setup();app.node('extra-detection').checked=true;app.context.window.applySettingsDefaults({...defaults,minimum_gap:.1});assert.equal(app.node('extra-detection').checked,true);
 app.context.window.applySettingsDefaults({...defaults,default_eye_search:true,default_directory_view:'list'});assert.equal(app.node('eye-search').checked,true);assert.equal(app.context.directoryListView,true);
 app.node('settings-theme').value='pop';app.node('settings-theme').handlers.change();assert.equal(app.context.document.documentElement.dataset.theme,'pop');assert.equal(app.calls.length,0);
}
{
 const app=setup();app.open();await app.settle();app.input('model','ArcFace');
 assert.equal(app.node('settings-model-change').hidden,false);assert.equal(app.node('settings-save').disabled,true);
 await app.submit();assert.equal(app.calls.filter(call=>call.payload).length,0);
 app.node('settings-confirm-model').checked=true;app.node('settings-form').handlers.change();
 assert.equal(app.node('settings-save').disabled,false);await app.submit();
 assert.equal(app.calls.find(call=>call.payload).payload.confirm_model_change,true);
 assert.equal(app.node('settings-model-change').hidden,true);
}
{
 const app=setup();app.open();await app.settle();app.input('model','ArcFace');app.node('settings-confirm-model').checked=true;
 app.input('model','GhostFaceNet');assert.equal(app.node('settings-confirm-model').checked,false);assert.equal(app.node('settings-save').disabled,true);
}
{
 const app=setup({cosine_distance_threshold:.21,minimum_gap:.08});
 app.setCatalog({model_profiles:{Facenet512:{cosine_distance_threshold:.21,minimum_gap:.08,calibrated:false},ArcFace:{cosine_distance_threshold:.44,minimum_gap:.12,calibrated:false}}});
 app.open();await app.settle();app.input('model','ArcFace');
 assert.equal(app.node('pref-cosine_distance_threshold').value,'0.44');assert.equal(app.node('pref-minimum_gap').value,'0.12');
 assert.match(app.node('settings-calibration-status').textContent,/ArcFace · Uncalibrated/);
 app.input('cosine_distance_threshold',.45);app.input('model','Facenet512');
 assert.equal(app.node('pref-cosine_distance_threshold').value,'0.21');app.input('model','ArcFace');
 assert.equal(app.node('pref-cosine_distance_threshold').value,'0.45');
}
console.log('PASS: 8 settings interface checks (save, staged defaults, stale drafts, active-scan refresh, capture defaults and immediate theme).');
