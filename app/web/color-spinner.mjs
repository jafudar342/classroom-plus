import {COLORS,SLICE,normalize,pointerIndex,polar,sectorPath,randomIndex,createSpinPlan,easeOut,labelColor} from './spinner-core.mjs';

const $=id=>document.getElementById(id);
const dialog=$('color-spinner-dialog'),trigger=$('color-spinner-trigger'),wheel=$('spinner-segments');
const namespace='http://www.w3.org/2000/svg';
let rotation=0,frame=null,spinning=false,startRotation=0,lastPick=null,copySequence=0;
const history=[];
function svg(tag,attributes) {
  const element=document.createElementNS(namespace,tag);
  for(const [key,value] of Object.entries(attributes))element.setAttribute(key,String(value));
  return element;
}
for(const [index,color] of COLORS.entries()) {
  const section=svg('g',{'data-color-index':index});
  section.append(svg('path',{d:sectorPath(index),fill:color.hex,class:'spinner-sector'}));
  const [x,y]=polar(-90+index*SLICE,163);
  const label=svg('text',{x,y,fill:labelColor(color.hex),'text-anchor':'middle','dominant-baseline':'middle',transform:`rotate(${index*SLICE} ${x} ${y})`,class:'spinner-sector-label'});
  label.textContent=color.name;
  section.append(label);wheel.append(section);
  const chip=document.createElement('li');
  const dot=svg('svg',{viewBox:'0 0 16 16','aria-hidden':'true'});
  dot.append(svg('circle',{cx:8,cy:8,r:7,fill:color.hex}));
  const name=document.createElement('span');name.textContent=color.name;
  chip.append(dot,name);$('spinner-palette').append(chip);
}
function paint(angle) {rotation=angle;wheel.setAttribute('transform',`rotate(${angle} 240 240)`);}
function showResult(index) {
  const color=index===null?null:COLORS[index];
  $('spinner-result-card').dataset.empty=String(!color);
  $('spinner-result-label').textContent=color?'THE WHEEL PICKED':'LEAVE IT TO THE WHEEL';
  $('spinner-result-name').textContent=color?color.name:'A little color, by chance.';
  $('spinner-result-hex').value=color?color.hex:'—';
  $('spinner-result-fill').setAttribute('fill',color?color.hex:'currentColor');
  $('spinner-copy').disabled=!color;
  $('spinner-copy').textContent='Copy hex';
}
function controls(running) {
  spinning=running;dialog.classList.toggle('is-spinning',running);
  $('spinner-spin').disabled=running;
  $('spinner-spin').textContent=running?'Spinning…':lastPick===null?'Spin the wheel ✦':'Spin again ✦';
  $('spinner-copy').disabled=running||lastPick===null;
  $('spinner-wheel').setAttribute('aria-busy',String(running));
}
function addHistory(index) {
  history.unshift(index);history.splice(5);
  $('spinner-history-wrap').hidden=false;
  $('spinner-history').replaceChildren(...history.map(value=>{
    const color=COLORS[value],chip=document.createElement('span');
    const dot=svg('svg',{viewBox:'0 0 16 16','aria-hidden':'true'});
    dot.append(svg('circle',{cx:8,cy:8,r:7,fill:color.hex}));
    const label=document.createElement('span');label.textContent=color.name;
    chip.append(dot,label);return chip;
  }));
}
function stop() {
  copySequence++;
  if(frame!==null)cancelAnimationFrame(frame);
  frame=null;
  if(spinning)paint(startRotation);
  showResult(lastPick);controls(false);
  $('spinner-status').textContent=lastPick===null?'16 colors. One pointer. Your next pick awaits.':`${COLORS[lastPick].name} · ${COLORS[lastPick].hex}. Spin again for another color.`;
}
function spin() {
  if(spinning||!dialog.open)return;
  copySequence++;
  const reduced=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const index=randomIndex(),turns=reduced?0:8+randomIndex(4);
  const jitter=(randomIndex(1001)/1000-.5)*SLICE*.5;
  const plan=createSpinPlan(index,rotation,turns,jitter),duration=reduced?180:6200+randomIndex(1001);
  startRotation=plan.start;controls(true);
  $('spinner-status').textContent=reduced?'Picking your color…':'Around we go… watch the pointer at the top.';
  let began=null;
  function animate(timestamp) {
    if(!spinning||!dialog.open)return;
    if(began===null)began=timestamp;
    const progress=Math.min(1,(timestamp-began)/duration);
    paint(plan.start+(plan.end-plan.start)*easeOut(progress));
    if(progress<1) {frame=requestAnimationFrame(animate);return;}
    frame=null;paint(normalize(plan.end));
    // Read the landed geometry so the announced color always agrees with the pointer.
    lastPick=pointerIndex(rotation);showResult(lastPick);controls(false);addHistory(lastPick);
    $('spinner-status').textContent=`${COLORS[lastPick].name}! The pointer landed on ${COLORS[lastPick].hex}.`;
  }
  frame=requestAnimationFrame(animate);
}
trigger.addEventListener('click',()=>{
  if(document.querySelector('dialog[open]'))return;
  document.getElementById('stop-camera').click();
  dialog.showModal();$('spinner-spin').focus();
});
$('spinner-spin').addEventListener('click',spin);
$('spinner-close').addEventListener('click',()=>dialog.close());
dialog.addEventListener('close',()=>{stop();trigger.focus();});
$('spinner-copy').addEventListener('click',async()=>{
  if(spinning||lastPick===null)return;
  const sequence=++copySequence,color=COLORS[lastPick];
  try {
    await navigator.clipboard.writeText(color.hex);
    if(sequence!==copySequence||!dialog.open)return;
    $('spinner-copy').textContent='Copied ✓';
    $('spinner-status').textContent=`${color.hex} copied. Make something colorful.`;
  } catch {
    if(sequence!==copySequence||!dialog.open)return;
    $('spinner-result-hex').focus();$('spinner-result-hex').select();
    $('spinner-status').textContent='Select the hex code and copy it with your keyboard.';
  }
});
showResult(null);
