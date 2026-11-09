import { expect, test } from 'vitest';
import { parseFen } from './board.js';

const initial = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
const labels = (fen: string, color: 'white' | 'black' = 'white') =>
	parseFen(fen, color)?.map((s) => s.label);

test('renders 64 starting squares and rotates both axes for Black', () => {
	expect(labels(initial)).toHaveLength(64);
	expect(labels(initial)?.[0]).toBe('a8: Black rook');
	expect(labels(initial)?.[60]).toBe('e1: White king');
	expect(labels(initial, 'black')?.[0]).toBe('h1: White rook');
	expect(labels(initial, 'black')?.[63]).toBe('a8: Black rook');
});

test.each([
	['8/8/8/8/8/8/8/8 w - - 0 1', 0, 'a8: empty'],
	['r1bqkb1r/pppp1ppp/2n2n2/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 4 4', 18, 'c6: Black knight'],
	['8/4k3/3p4/3P4/8/4K3/8/8 w - - 0 45', 27, 'd5: White pawn'],
	['Q7/7k/8/8/8/8/8/7K b - - 0 54', 0, 'a8: White queen']
])('preserves square contents for %s', (fen, index, expected) => {
	expect(labels(fen)).toHaveLength(64);
	expect(labels(fen)?.[index]).toBe(expected);
});

test.each([
	'bad',
	'8/8/8/8/8/8/8/9 w - - 0 1',
	'8/8/8/8/8/8/8/44 w - - 0 1',
	'8/8/8/8/8/8/8/8 y - - 0 1'
])('rejects invalid FEN %s', (fen) => {
	expect(parseFen(fen)).toBeNull();
});
