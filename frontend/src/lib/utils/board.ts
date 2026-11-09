const files = 'abcdefgh';
const names = {
	p: 'pawn',
	n: 'knight',
	b: 'bishop',
	r: 'rook',
	q: 'queen',
	k: 'king'
} as const;
const pieces = 'KQRBNPkqrbnp';

export type Square = { coordinate: string; piece: string; label: string; dark: boolean };

export function parseFen(fen: string, orientation: 'white' | 'black' = 'white'): Square[] | null {
	const parts = fen.trim().split(/\s+/);
	if (parts.length !== 6) return null;
	const [placement, turn, castling, enPassant, halfmove, fullmove] = parts;
	if (
		!/^[wb]$/.test(turn) ||
		!/^(?:-|(?=[KQkq])K?Q?k?q?)$/.test(castling) ||
		!/^(?:-|[a-h][36])$/.test(enPassant) ||
		!/^\d+$/.test(halfmove) ||
		!/^[1-9]\d*$/.test(fullmove)
	)
		return null;

	const ranks = placement.split('/');
	if (ranks.length !== 8) return null;
	const squares: Square[] = [];
	for (const [row, rank] of ranks.entries()) {
		if (!/^[KQRBNPkqrbnp1-8]+$/.test(rank) || /\d\d/.test(rank)) return null;
		const expanded = rank.replace(/[1-8]/g, (digit) => '.'.repeat(Number(digit)));
		if (expanded.length !== 8) return null;
		for (const [file, symbol] of [...expanded].entries()) {
			const coordinate = files[file] + (8 - row);
			const color = symbol === symbol.toUpperCase() ? 'White' : 'Black';
			const name = names[symbol.toLowerCase() as keyof typeof names];
			squares.push({
				coordinate,
				piece: pieces.includes(symbol) ? symbol : '',
				label: `${coordinate}: ${name ? color + ' ' + name : 'empty'}`,
				dark: (file + row) % 2 === 1
			});
		}
	}
	return orientation === 'black' ? squares.reverse() : squares;
}

export function endpoints(uci?: string | null) {
	return uci && /^[a-h][1-8][a-h][1-8][qrbn]?$/.test(uci) ? [uci.slice(0, 2), uci.slice(2, 4)] : [];
}
