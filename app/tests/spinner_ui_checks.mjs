import fs from 'node:fs/promises';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import * as core from '../web/spinner-core.mjs';
const source=(await fs.readFile(new URL('../web/color-spinner.mjs',import.meta.url),'utf8')).replace(/^import[^\n]+\n/,'');
function setup(reduced=false) {
  const nodes=new Map(),frames=new Map(),copied=[];let nextFrame=0;
  function element(id='') {return {id,attrs:{},dataset:{},children:[],handlers:{},disabled:false,open:false,clicks:0,classList:{toggle(){}},
    setAttribute(key,value){this.attrs[key]=String(value);},append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;},
    addEventListener(key,fn){this.handlers[key]=fn;},click(){this.clicks++;return this.handlers.click?.();},focus(){this.focused=true;},select(){this.selected=true;},
    showModal(){this.open=true;},close(){this.open=false;this.handlers.close?.();}};}
  const node=id=>{if(!nodes.has(id))nodes.set(id,element(id));return nodes.get(id);};
  const context=vm.createContext({...core,randomIndex:(length=16)=>length===16?3:0,
    document:{getElementById:node,createElement:()=>element(),createElementNS:()=>element(),querySelector:()=>node('color-spinner-dialog').open?node('color-spinner-dialog'):null},
    window:{matchMedia:()=>({matches:reduced})},navigator:{clipboard:{writeText:async value=>{copied.push(value);}}},
    requestAnimationFrame(fn){const id=++nextFrame;frames.set(id,fn);return id;},cancelAnimationFrame(id){frames.delete(id);}});
  vm.runInContext(source,context);
  return {node,frames,copied,context,step(timestamp){const pending=[...frames.values()];frames.clear();pending.forEach(fn=>fn(timestamp));},open(){node('color-spinner-trigger').click();},spin(){node('spinner-spin').click();},close(){node('color-spinner-dialog').close();}};
}
{
 const app=setup();assert.equal(app.node('spinner-segments').children.length,16);assert.equal(app.node('spinner-palette').children.length,16);
 app.open();assert.equal(app.node('stop-camera').clicks,1);app.spin();app.spin();assert.equal(app.frames.size,1);assert.equal(app.node('spinner-spin').disabled,true);
 app.step(0);app.step(8000);assert.equal(app.node('spinner-spin').disabled,false);assert.equal(app.node('spinner-result-name').textContent,'Amber');assert.equal(app.node('spinner-result-hex').value,'#F8BD42');
 await app.node('spinner-copy').click();assert.deepEqual(app.copied,['#F8BD42']);assert.equal(app.node('spinner-history').children.length,1);
}
{
 const app=setup();app.open();app.spin();app.step(0);app.step(1000);app.close();assert.equal(app.frames.size,0);assert.equal(app.node('spinner-segments').attrs.transform,'rotate(0 240 240)');
 assert.equal(app.node('spinner-result-hex').value,'—');app.open();assert.equal(app.node('spinner-spin').disabled,false);
}
{
 const app=setup(true);app.open();app.spin();app.step(0);app.step(200);assert.equal(app.frames.size,0);assert.equal(app.node('spinner-result-name').textContent,'Amber');
}
{
 const app=setup();app.open();for(let n=0;n<7;n++){app.spin();app.step(0);app.step(8000);}assert.equal(app.node('spinner-history').children.length,5);
}
console.log('PASS: spinner interface checks (16 sections, duplicate-click guard, matching result, copy, cancel/reopen, reduced motion, bounded history).');
