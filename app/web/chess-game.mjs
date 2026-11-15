import { Chess } from './vendor/chess.mjs';

const game = new Chess();
const $ = id => document.getElementById(id);
const symbols = {wk:'♚', wq:'♛', wr:'♜', wb:'♝', wn:'♞', wp:'♟', bk:'♚', bq:'♛', br:'♜', bb:'♝', bn:'♞', bp:'♟'};
const names = {p:'pawn', n:'knight', b:'bishop', r:'rook', q:'queen', k:'king'};
let selected = null;
let flipped = false;
let pending = null;
let focusSquare = null;

function render() {
  const turn = game.turn() === 'w' ? 'White' : 'Black';
  let status = `${turn} to move`;
  if (game.isCheckmate()) status = `Checkmate · ${turn === 'White' ? 'Black' : 'White'} wins`;
  else if (game.isStalemate()) status = 'Draw · stalemate';
  else if (game.isThreefoldRepetition()) status = 'Draw · threefold repetition';
  else if (game.isInsufficientMaterial()) status = 'Draw · insufficient material';
  else if (game.isDraw()) status = 'Draw · fifty-move rule';
  else if (game.isCheck()) status += ' · check';
  $('status').textContent = status;
  const legal = selected ? game.moves({square:selected, verbose:true}) : [];
  const history = game.history({verbose:true});
  const last = history.at(-1);
  $('board').replaceChildren();
  for (let row=0; row<8; row++) {
    for (let column=0; column<8; column++) {
      const rank = flipped ? row+1 : 8-row;
      const file = String.fromCharCode(97 + (flipped ? 7-column : column));
      const square = file + rank;
      const piece = game.get(square);
      const target = legal.some(move => move.to === square);
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.square = square;
      button.className = `square ${(row+column)%2 ? 'dark' : 'light'}`;
      button.classList.toggle('selected', selected === square);
      button.classList.toggle('target', target);
      button.classList.toggle('last', last?.from === square || last?.to === square);
      button.classList.toggle('check', Boolean(piece?.type === 'k' && piece.color === game.turn() && game.isCheck()));
      const description = piece ? `${piece.color === 'w' ? 'White' : 'Black'} ${names[piece.type]}` : 'empty';
      button.setAttribute('aria-label', `${square}, ${description}${target ? ', legal move' : ''}`);
      button.setAttribute('aria-pressed', String(selected === square));
      if (piece) {
        const span = document.createElement('span');
        span.className = `piece ${piece.color === 'w' ? 'white-piece' : 'black-piece'}`;
        span.textContent = symbols[piece.color + piece.type];
        span.setAttribute('aria-hidden','true');
        button.append(span);
      }
      const coordinate = document.createElement('small');
      coordinate.textContent = square;
      coordinate.setAttribute('aria-hidden','true');
      button.append(coordinate);
      $('board').append(button);
    }
  }
  $('moves').replaceChildren();
  for (let index=0; index<history.length; index+=2) {
    const item = document.createElement('li');
    item.textContent = `${history[index].san}     ${history[index+1]?.san || ''}`;
    $('moves').append(item);
  }
  $('moves').scrollTop = $('moves').scrollHeight;
  if (focusSquare) $('board').querySelector('[data-square="' + focusSquare + '"]').focus({preventScroll:true});
  $('undo').disabled = !history.length || Boolean(pending);
  $('promotion').hidden = !pending;
}

function play(from, to, promotion) {
  game.move({from,to,...(promotion ? {promotion} : {})});
  selected = null;
  pending = null;
  render();
}
$('board').addEventListener('click', event => {
  const square = event.target.closest('[data-square]')?.dataset.square;
  if (!square || pending || game.isGameOver()) return;
  focusSquare = square;
  const candidates = selected ? game.moves({square:selected,verbose:true}).filter(move => move.to === square) : [];
  if (candidates.length) {
    if (candidates.some(move => move.promotion)) {
      pending = {from:selected,to:square};
      render();
      $('promotion').querySelector('button').focus();
    } else play(selected,square);
    return;
  }
  const piece = game.get(square);
  selected = piece?.color === game.turn() && selected !== square ? square : null;
  render();
});
$('promotion').addEventListener('click', event => {
  const piece = event.target.closest('[data-piece]')?.dataset.piece;
  if (pending && piece) play(pending.from,pending.to,piece);
});
$('promotion-cancel').addEventListener('click', () => { pending=null; selected=null; render(); });
$('undo').addEventListener('click', () => { if (pending) return; game.undo(); selected=null; render(); });
$('flip').addEventListener('click', () => { flipped=!flipped; render(); });
$('new').addEventListener('click', () => { $('reset-confirm').hidden=false; $('reset-yes').focus(); });
$('reset-no').addEventListener('click', () => { $('reset-confirm').hidden=true; });
$('reset-yes').addEventListener('click', () => {
  game.reset(); selected=null; pending=null;
  $('reset-confirm').hidden=true; render();
});
render();
