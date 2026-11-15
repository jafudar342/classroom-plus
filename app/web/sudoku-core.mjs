export const LEVELS=Object.freeze({easy:42,medium:34,hard:28});
export function peers(index) {
  const row=Math.floor(index/9),column=index%9;
  return Array.from({length:81},(_,i)=>i).filter(i=>i!==index&&(Math.floor(i/9)===row||i%9===column||(Math.floor(i/27)===Math.floor(row/3)&&Math.floor(i%9/3)===Math.floor(column/3))));
}
export const PEERS=Object.freeze(Array.from({length:81},(_,i)=>Object.freeze(peers(i))));
export function conflicts(board) {
  return board.map((value,index)=>Boolean(value&&PEERS[index].some(peer=>board[peer]===value)));
}
export function countSolutions(input,limit=2) {
  if(!Array.isArray(input))return 0;
  const board=[...input];
  if(board.length!==81||board.some(value=>!Number.isInteger(value)||value<0||value>9)||conflicts(board).some(Boolean))return 0;
  function search() {
    let chosen=-1,choices=null;
    for(let index=0;index<81;index++)if(!board[index]) {
      const used=new Set(PEERS[index].map(peer=>board[peer]));
      const available=[1,2,3,4,5,6,7,8,9].filter(value=>!used.has(value));
      if(!available.length)return 0;
      if(choices===null||available.length<choices.length){chosen=index;choices=available;if(choices.length===1)break;}
    }
    if(chosen===-1)return 1;
    let total=0;
    for(const value of choices){board[chosen]=value;total+=search();if(total>=limit)break;}
    board[chosen]=0;return Math.min(total,limit);
  }
  return search();
}
function shuffled(values,random) {
  const result=[...values];
  for(let i=result.length-1;i>0;i--){const j=Math.floor(random()*(i+1));[result[i],result[j]]=[result[j],result[i]];}
  return result;
}
export function createPuzzle(level='easy',random=Math.random) {
  if(!Object.hasOwn(LEVELS,level))throw new Error('Choose a valid Sudoku difficulty.');
  let best=null;
  for(let attempt=0;attempt<3;attempt++) {
    const groups=()=>shuffled([0,1,2],random).flatMap(group=>shuffled([0,1,2],random).map(offset=>group*3+offset));
    const rows=groups(),columns=groups(),digits=shuffled([1,2,3,4,5,6,7,8,9],random);
    const solution=rows.flatMap(row=>columns.map(column=>digits[(row*3+Math.floor(row/3)+column)%9]));
    const givens=[...solution];let clues=81;
    for(const index of shuffled(Array.from({length:81},(_,i)=>i),random)) {
      if(clues<=LEVELS[level])break;
      const value=givens[index];givens[index]=0;
      if(countSolutions(givens)===1)clues--;else givens[index]=value;
    }
    if(!best||clues<best.clues)best={level,givens,solution,clues};
    if(clues<=LEVELS[level])break;
  }
  return best;
}
export function solved(board) {return Array.isArray(board)&&board.length===81&&board.every(value=>Number.isInteger(value)&&value>=1&&value<=9)&&!conflicts(board).some(Boolean);}
export function validSavedGame(game) {
  if(!game||game.version!==1||!Object.hasOwn(LEVELS,game.level)||!solved(game.solution))return false;
  const validBoard=values=>Array.isArray(values)&&values.length===81&&values.every(value=>Number.isInteger(value)&&value>=0&&value<=9);
  if(!validBoard(game.givens)||!validBoard(game.board)||!Array.isArray(game.notes)||game.notes.length!==81||game.notes.some(value=>!Number.isInteger(value)||value<0||value>511))return false;
  if(game.givens.filter(Boolean).length<17||game.givens.some((value,index)=>value&&(value!==game.solution[index]||value!==game.board[index])))return false;
  if(game.board.some((value,index)=>value&&game.notes[index]))return false;
  return Number.isFinite(game.elapsed)&&game.elapsed>=0&&game.elapsed<=31536000000&&Number.isInteger(game.hints)&&game.hints>=0&&game.hints<=100000&&countSolutions(game.givens)===1;
}
