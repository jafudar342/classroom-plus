import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
const source=await fs.readFile(new URL('../web/theme.js',import.meta.url),'utf8');
const key='classroom-attendance-theme';
function setup({saved=null,systemDark=false,blocked=false}={}) {
  const values=new Map(saved===null?[]:[[key,saved]]),events={},meta={},root={dataset:{}};
  function element(id,dataset={}) {return {id,dataset,attrs:{},handlers:{},focused:false,hidden:false,setAttribute(k,v){this.attrs[k]=v;},focus(){this.focused=true;},addEventListener(k,fn){this.handlers[k]=fn;}};}
  const button=element('theme-toggle'),popup=element('theme-options'),wrapper=element('theme-switcher');popup.hidden=true;
  const choices=['light','dark','pop','oled'].map(theme=>element(theme,{themeChoice:theme}));
  wrapper.contains=target=>[wrapper,button,popup,...choices].includes(target);
  const media={matches:systemDark,addEventListener(k,fn){events['media:'+k]=fn;}};
  let ready=false;
  const context=vm.createContext({document:{documentElement:root,
    querySelector(selector){if(selector.startsWith('meta'))return {setAttribute(k,v){meta[k]=v;}};return ready?choices.find(option=>selector===`[data-theme-choice="${option.id}"]`):null;},
    querySelectorAll(){return ready?choices:[];},getElementById(id){return ready?({'theme-toggle':button,'theme-options':popup,'theme-switcher':wrapper}[id] || null):null;},
    addEventListener(k,fn){events['document:'+k]=fn;}},window:{matchMedia:()=>media,addEventListener(k,fn){events['window:'+k]=fn;}},
    localStorage:{getItem(k){if(blocked)throw new Error('blocked');return values.get(k)??null;},setItem(k,v){if(blocked)throw new Error('blocked');values.set(k,v);}}});
  vm.runInContext(source,context);
  return {root,button,popup,wrapper,choices,meta,values,events,media,
    ready(){ready=true;events['document:DOMContentLoaded']();},open(){button.handlers.click();},choose(theme){choices.find(option=>option.id===theme).handlers.click();},storage(event){events['window:storage'](event);}};
}
{
  const app=setup({systemDark:true});assert.equal(app.root.dataset.theme,'dark');assert.equal(app.meta.content,'#11192d');
  app.ready();assert.match(app.button.attrs['aria-label'],/current theme: Dark/);
}
{
  const app=setup({saved:'light',systemDark:true});app.ready();assert.equal(app.root.dataset.theme,'light');
}
{
  const app=setup({saved:'pop'});assert.equal(app.root.dataset.theme,'pop');assert.equal(app.meta.content,'#171125');
  app.ready();assert.match(app.button.attrs['aria-label'],/current theme: Pop/);assert.equal(app.choices[2].attrs['aria-pressed'],'true');
}
{
  const app=setup();app.ready();app.open();assert.equal(app.popup.hidden,false);assert.equal(app.button.attrs['aria-expanded'],'true');assert.equal(app.choices[0].focused,true);
  app.choose('pop');assert.equal(app.popup.hidden,true);assert.equal(app.values.get(key),'pop');assert.equal(app.button.focused,true);
  assert.equal(setup({saved:app.values.get(key)}).root.dataset.theme,'pop');
}
{
  const app=setup();app.ready();for(const theme of ['dark','pop','oled','light']){app.open();app.choose(theme);assert.equal(app.root.dataset.theme,theme);assert.equal(app.values.get(key),theme);}
  assert.equal(app.choices.filter(option=>option.attrs['aria-pressed']==='true').length,1);
}
{
  const app=setup();app.ready();app.media.matches=true;app.events['media:change']();assert.equal(app.root.dataset.theme,'dark');
}
{
  const app=setup({saved:'pop'});app.ready();app.media.matches=true;app.events['media:change']();assert.equal(app.root.dataset.theme,'pop');
}
{
  const app=setup({saved:'invalid',systemDark:true});assert.equal(app.root.dataset.theme,'dark');
}
{
  const app=setup({blocked:true});app.ready();assert.doesNotThrow(()=>app.choose('pop'));assert.equal(app.root.dataset.theme,'pop');assert.equal(app.popup.hidden,true);
}
{
  const app=setup();app.ready();app.storage({key,newValue:'pop'});assert.equal(app.root.dataset.theme,'pop');
  app.storage({key:'another-app',newValue:'light'});assert.equal(app.root.dataset.theme,'pop');
  app.storage({key:null,newValue:null});assert.equal(app.root.dataset.theme,'light');
}
{
  const app=setup();app.ready();app.open();let prevented=false;
  app.events['document:keydown']({key:'Escape',preventDefault(){prevented=true;}});
  assert.equal(app.popup.hidden,true);assert.equal(app.button.focused,true);assert.equal(prevented,true);
}
{
  const app=setup();app.ready();app.open();app.events['document:click']({target:{}});assert.equal(app.popup.hidden,true);
  app.open();app.wrapper.handlers.focusout({relatedTarget:{}});assert.equal(app.popup.hidden,true);
}
console.log('PASS: 12 theme checks (all four themes, first paint, saved preference, system default, keyboard focus, dismissal, blocked storage, and tab synchronization).');
