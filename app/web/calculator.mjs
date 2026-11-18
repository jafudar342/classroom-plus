import {Calculator} from './calculator-core.mjs';
const calc=new Calculator(),dialog=document.getElementById('calculator-dialog');
const keys=document.getElementById('calculator-keys');
const labels={'⌫':'Backspace','±':'Change sign','%':'Divide by 100','/':'Divide','*':'Multiply','-':'Subtract','+':'Add','=':'Equals','AC':'Clear all'};
const symbols={'/':'÷','*':'×','-':'−'};
function press(key){
  document.getElementById('calculator-display').textContent=calc.press(key);
  document.getElementById('calculator-operation').textContent=calc.operator?`${calc.value} ${symbols[calc.operator]||calc.operator}`:'';
}
for(const key of ['AC','±','%','⌫','7','8','9','/','4','5','6','*','1','2','3','-','0','.','=','+']){
  const button=document.createElement('button');button.type='button';button.className=`button ${key==='='?'primary':'secondary'}`;button.textContent=symbols[key]||key;button.setAttribute('aria-label',labels[key]||key);button.onclick=()=>press(key);keys.append(button);
}
document.getElementById('calculator-trigger').onclick=()=>dialog.showModal();
document.getElementById('calculator-close').onclick=()=>dialog.close();
dialog.addEventListener('keydown',event=>{
  if(event.ctrlKey||event.metaKey||event.altKey)return;
  const key=event.key==='Enter'?'=':event.key==='Backspace'?'⌫':event.key==='Delete'?'AC':event.key;
  if(/^[0-9.+*/%=-]$/.test(key)||['⌫','AC'].includes(key)){event.preventDefault();press(key);}
});
