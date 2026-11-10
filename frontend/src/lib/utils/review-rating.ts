import type { ReviewRating } from '#lib/api/review.js';

export const moveRatings: Record<
	ReviewRating,
	{ label: string; symbol: string; tone: string; explanation: string }
> = {
	brilliant: {
		label: 'Brilliant',
		symbol: '‼',
		tone: 'text-cyan-400',
		explanation:
			'Stockfish’s top move gives up material in the saved line and keeps a non-losing evaluation.'
	},
	great: {
		label: 'Great',
		symbol: '!',
		tone: 'text-blue-400',
		explanation:
			'Stockfish’s top move delivers checkmate or gives double check while keeping a non-losing evaluation.'
	},
	best: {
		label: 'Best',
		symbol: '★',
		tone: 'text-lime-400',
		explanation: 'This was Stockfish’s top move.'
	},
	book: {
		label: 'Book',
		symbol: '▤',
		tone: 'text-amber-200',
		explanation: 'This move follows a known opening line and kept the engine evaluation close.'
	},
	good: {
		label: 'Good',
		symbol: '✓',
		tone: 'text-green-400',
		explanation: 'Stockfish’s evaluation changed little or improved for the player who moved.'
	},
	inaccuracy: {
		label: 'Inaccuracy',
		symbol: '?!',
		tone: 'text-orange-400',
		explanation: 'The evaluation dropped slightly for the player who moved.'
	},
	mistake: {
		label: 'Mistake',
		symbol: '×',
		tone: 'text-rose-300',
		explanation: 'The evaluation dropped significantly for the player who moved.'
	},
	miss: {
		label: 'Miss',
		symbol: '?',
		tone: 'text-fuchsia-400',
		explanation:
			'Stockfish saw a forced mate before this move. The saved evaluation after it no longer shows that mate.'
	},
	blunder: {
		label: 'Blunder',
		symbol: '⁇',
		tone: 'text-red-400',
		explanation: 'The evaluation dropped sharply for the player who moved.'
	},
	unrated: {
		label: 'Unrated',
		symbol: '·',
		tone: 'text-stone-400',
		explanation: 'The saved engine evidence does not support a rating for this move.'
	}
};
