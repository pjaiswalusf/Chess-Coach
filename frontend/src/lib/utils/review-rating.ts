import type { ReviewRating } from '#lib/api/review.js';

export const moveRatings: Record<ReviewRating, { label: string; symbol: string; tone: string }> = {
	brilliant: { label: 'Brilliant', symbol: '!!', tone: 'text-[#26c3a2]' },
	great: { label: 'Great', symbol: '!', tone: 'text-[#749bbf]' },
	book: { label: 'Book', symbol: 'book', tone: 'text-[#d5a47d]' },
	best: { label: 'Best', symbol: 'star', tone: 'text-[#81b64c]' },
	excellent: { label: 'Excellent', symbol: 'thumb', tone: 'text-[#81b64c]' },
	good: { label: 'Good', symbol: 'check', tone: 'text-[#95b776]' },
	inaccuracy: { label: 'Inaccuracy', symbol: '?!', tone: 'text-[#f7c631]' },
	mistake: { label: 'Mistake', symbol: '?', tone: 'text-[#ffa459]' },
	miss: { label: 'Miss', symbol: 'cross', tone: 'text-[#ff7769]' },
	blunder: { label: 'Blunder', symbol: '??', tone: 'text-[#fa412d]' }
};
