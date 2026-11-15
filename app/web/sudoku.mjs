import {PEERS,createPuzzle,conflicts,solved,validSavedGame} from './sudoku-core.mjs';
const $=id=>document.getElementById(id),dialog=$('sudoku-dialog'),trigger=$('sudoku-trigger'),key='classroom-plus-sudoku-v1';
let game=null,selection=0,notesMode=false,history=[],checked=new Set(),started=null,lastSaved=0;
const cells=[];
for(let row=0;row<9;row++) {
  const line=document.createElement('div');line.className='sudoku-row';line.setAttribute('role','row');
  if(row===2||row===5)line.classList.add('sudoku-box-bottom');
  for(let column=0;column<9;column++) {
    const index=row*9+column,button=document.createElement('button');button.type='button';button.className='sudoku-cell';button.setAttribute('role','gridcell');
    if(column===2||column===5)button.classList.add('sudoku-box-right');
    const digit=document.createElement('span');digit.className='sudoku-digit';
    const notes=document.createElement('span');notes.className='sudoku-cell-notes';notes.setAttribute('aria-hidden','true');
    const marks=Array.from({length:9},()=>document.createElement('span'));notes.append(...marks);button.append(digit,notes);
    button.addEventListener('click',()=>{selection=index;render();button.focus();});line.append(button);cells.push({button,digit,notes,marks});
  }
  $('sudoku-grid').append(line);
}
for(let digit=1;digit<=9;digit++) {
  const button=document.createElement('button');button.type='button';button.textContent=String(digit);button.setAttribute('aria-label',`Enter ${digit}`);button.addEventListener('click',()=>enter(digit));$('sudoku-numbers').append(button);
}
function elapsed(){return (game?.elapsed||0)+(started===null?0:Math.max(0,Date.now()-started));}
function stamp(milliseconds){const seconds=Math.floor(milliseconds/1000),minutes=Math.floor(seconds/60);return `${String(minutes).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`;}
function pause(){if(game&&started!==null){game.elapsed=elapsed();started=null;}}
function resume(){if(game&&dialog.open&&!document.hidden&&!game.won&&started===null)started=Date.now();}
function save(){if(!game)return;try{localStorage.setItem(key,JSON.stringify({...game,elapsed:elapsed()}));$('sudoku-save-note').textContent='Progress saved in this browser.';}catch{$('sudoku-save-note').textContent='Progress lasts for this visit. Browser saving is unavailable.';}lastSaved=Date.now();}
function status(message){$('sudoku-status').textContent=message;}
function render() {
  if(!game)return;
  const invalid=conflicts(game.board),value=game.board[selection];
  cells.forEach(({button,digit,notes,marks},index)=>{
    const number=game.board[index],given=Boolean(game.givens[index]),bad=invalid[index]||checked.has(index);
    button.tabIndex=index===selection?0:-1;button.classList.toggle('given',given);button.classList.toggle('selected',index===selection);
    button.classList.toggle('peer',PEERS[selection].includes(index));button.classList.toggle('same-number',Boolean(value&&number===value));button.classList.toggle('invalid',bad);
    button.setAttribute('aria-selected',String(index===selection));button.setAttribute('aria-readonly',String(given));button.setAttribute('aria-invalid',String(bad));
    const pencil=marks.map((mark,offset)=>{const present=!number&&Boolean(game.notes[index]&(1<<offset));mark.textContent=present?String(offset+1):'';return present?offset+1:null;}).filter(Boolean);
    digit.textContent=number?String(number):'';notes.hidden=Boolean(number);
    button.setAttribute('aria-label',`Row ${Math.floor(index/9)+1}, column ${index%9+1}, ${given?'given ':''}${number||'empty'}${pencil.length?', notes '+pencil.join(', '):''}${bad?', needs review':''}`);
  });
  $('sudoku-filled').textContent=`${game.board.filter(Boolean).length} / 81 filled`;
  $('sudoku-timer').textContent=stamp(elapsed());$('sudoku-hint-count').textContent=`${game.hints} hint${game.hints===1?'':'s'} used`;
  $('sudoku-level-label').textContent=game.level[0].toUpperCase()+game.level.slice(1);
  $('sudoku-notes').setAttribute('aria-pressed',String(notesMode));$('sudoku-notes').textContent=notesMode?'Notes on ✎':'Notes ✎';
  $('sudoku-undo').disabled=!history.length;$('sudoku-erase').disabled=Boolean(game.givens[selection])||game.won;
  $('sudoku-numbers').querySelectorAll('button').forEach(button=>{button.disabled=Boolean(game.givens[selection])||game.won;});
  $('sudoku-hint').disabled=game.won;$('sudoku-complete').hidden=!game.won;
  $('sudoku-complete-detail').textContent=`${stamp(elapsed())} of play · ${game.hints} hint${game.hints===1?'':'s'} used`;
}
function remember(){history.push({board:[...game.board],notes:[...game.notes],selection});if(history.length>200)history.shift();}
function changed(message) {
  game.won=solved(game.board);
  if(game.won){pause();message='Solved! Every row, column and box is complete.';}else resume();
  status(message);render();save();
}
function enter(value) {
  if(!game||game.won||game.givens[selection])return;
  if(notesMode&&value&&game.board[selection]){status('Erase this entry before adding pencil notes.');return;}
  if(!value&&!game.board[selection]&&!game.notes[selection])return;
  remember();checked.delete(selection);
  if(notesMode&&value){game.notes[selection]^=1<<(value-1);changed('Pencil notes updated.');return;}
  game.board[selection]=value;game.notes[selection]=0;
  if(value)for(const peer of PEERS[selection])game.notes[peer]&=~(1<<(value-1));
  changed(value?'Entry saved. Repeated numbers are highlighted.':'Cell cleared.');
}
function startNew() {
  pause();const puzzle=createPuzzle($('sudoku-difficulty').value);
  game={version:1,level:puzzle.level,givens:puzzle.givens,solution:puzzle.solution,board:[...puzzle.givens],notes:Array(81).fill(0),elapsed:0,hints:0,won:false};
  history=[];checked.clear();notesMode=false;selection=Math.max(0,game.givens.findIndex(value=>!value));$('sudoku-new-confirm').hidden=true;
  resume();status('Fresh puzzle ready. Every puzzle has exactly one solution.');render();save();cells[selection].button.focus();
}
trigger.addEventListener('click',()=>{
  if(document.querySelector('dialog[open]'))return;
  $('stop-camera').click();
  if(!game)try{const saved=JSON.parse(localStorage.getItem(key));if(validSavedGame(saved)){game=saved;game.won=solved(game.board);selection=Math.max(0,game.givens.findIndex(value=>!value));$('sudoku-difficulty').value=game.level;}}catch{/* Start fresh if a save is unavailable. */}
  dialog.showModal();
  if(!game)startNew();else{resume();status(game.won?'This puzzle is complete. Start a new one whenever you like.':'Welcome back. Your puzzle is right where you left it.');render();cells[selection].button.focus();}
});
$('sudoku-close').addEventListener('click',()=>dialog.close());
dialog.addEventListener('close',()=>{pause();save();$('sudoku-new-confirm').hidden=true;trigger.focus();});
$('sudoku-notes').addEventListener('click',()=>{notesMode=!notesMode;render();status(notesMode?'Notes on. Numbers become pencil marks in empty cells.':'Notes off. Numbers fill the selected cell.');});
$('sudoku-erase').addEventListener('click',()=>enter(0));
function undo(){if(!history.length)return;pause();const previous=history.pop();game.board=previous.board;game.notes=previous.notes;selection=previous.selection;checked.clear();changed('Last move undone.');}
$('sudoku-undo').addEventListener('click',undo);
$('sudoku-check').addEventListener('click',()=>{
  checked=new Set(game.board.flatMap((value,index)=>value&&value!==game.solution[index]?[index]:[]));
  status(checked.size?`${checked.size} entr${checked.size===1?'y needs':'ies need'} another look.`:game.won?'Solved — nicely done!':'No mistakes so far. Keep going!');render();
});
$('sudoku-hint').addEventListener('click',()=>{
  if(!game||game.won)return;
  let target=selection;
  if(game.givens[target]||game.board[target]===game.solution[target])target=game.board.findIndex((value,index)=>value!==game.solution[index]);
  if(target<0)return;remember();selection=target;game.board[target]=game.solution[target];game.notes[target]=0;
  for(const peer of PEERS[target])game.notes[peer]&=~(1<<(game.solution[target]-1));
  checked.delete(target);game.hints++;changed('One cell revealed. Use the rows, columns and boxes to find the next.');cells[target].button.focus();
});
$('sudoku-new').addEventListener('click',()=>{
  const progress=game&&!game.won&&(game.board.some((value,index)=>value!==game.givens[index])||game.notes.some(Boolean));
  if(progress){$('sudoku-new-confirm').hidden=false;$('sudoku-keep').focus();}else startNew();
});
$('sudoku-keep').addEventListener('click',()=>{$('sudoku-new-confirm').hidden=true;$('sudoku-new').focus();});
$('sudoku-replace').addEventListener('click',startNew);
$('sudoku-grid').addEventListener('keydown',event=>{
  let target=selection;const row=Math.floor(selection/9),column=selection%9;
  if(event.key==='ArrowUp')target=Math.max(0,row-1)*9+column;
  else if(event.key==='ArrowDown')target=Math.min(8,row+1)*9+column;
  else if(event.key==='ArrowLeft')target=row*9+Math.max(0,column-1);
  else if(event.key==='ArrowRight')target=row*9+Math.min(8,column+1);
  else if(event.key==='Home')target=row*9;
  else if(event.key==='End')target=row*9+8;
  else if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='z'){event.preventDefault();undo();return;}
  else if(!event.ctrlKey&&!event.metaKey&&!event.altKey&&/^[1-9]$/.test(event.key)){event.preventDefault();enter(Number(event.key));return;}
  else if(['Backspace','Delete','0'].includes(event.key)){event.preventDefault();enter(0);return;}
  else if(event.key.toLowerCase()==='n'){event.preventDefault();$('sudoku-notes').click();return;}
  else return;
  event.preventDefault();selection=target;render();cells[target].button.focus();
});
document.addEventListener('visibilitychange',()=>{if(document.hidden){pause();save();}else resume();});
window.addEventListener('pagehide',()=>{pause();save();});
setInterval(()=>{if(!game||!dialog.open)return;$('sudoku-timer').textContent=stamp(elapsed());if(Date.now()-lastSaved>15000)save();},1000);
