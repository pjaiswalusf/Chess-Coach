import type { ReviewRating } from '#lib/api/review.js';

export const moveRatings: Record<ReviewRating, { label: string; symbol: string; tone: string }> = {
	brilliant: {
		label: 'Brilliant',
		symbol: '‼',
		tone: 'text-cyan-400'
	},
	great: {
		label: 'Great',
		symbol: '!',
		tone: 'text-blue-400'
	},
	best: {
		label: 'Best',
		symbol: '★',
		tone: 'text-lime-400'
	},
	book: {
		label: 'Book',
		symbol: '▤',
		tone: 'text-amber-200'
	},
	good: {
		label: 'Good',
		symbol: '✓',
		tone: 'text-green-400'
	},
	inaccuracy: {
		label: 'Inaccuracy',
		symbol: '?!',
		tone: 'text-orange-400'
	},
	mistake: {
		label: 'Mistake',
		symbol: '×',
		tone: 'text-rose-300'
	},
	miss: {
		label: 'Miss',
		symbol: '?',
		tone: 'text-fuchsia-400'
	},
	blunder: {
		label: 'Blunder',
		symbol: '⁇',
		tone: 'text-red-400'
	},
	unrated: {
		label: 'Unrated',
		symbol: '·',
		tone: 'text-stone-400'
	}
};
