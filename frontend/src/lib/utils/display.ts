const date = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' });
const rate = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });

export function formatDate(value: string) {
	const parsed = new Date(value);
	return Number.isNaN(parsed.getTime()) ? 'Unknown date' : date.format(parsed);
}

export const formatRate = (value: number) => rate.format(value);
export const words = (value: string) => value.replace(/[_-]/g, ' ');
export const results = { win: 'Win', loss: 'Loss', draw: 'Draw', unknown: 'Unknown' } as const;

export type PositionScore = { cp: number | null; mate: number | null; whiteWins: boolean | null };

export function evaluationLabel(cp: number | null, mate: number | null, whiteWins: boolean | null) {
	if (cp !== null) return `${cp > 0 ? '+' : ''}${(cp / 100).toFixed(2)}`;
	if (mate !== null && whiteWins !== null) {
		const winner = whiteWins ? 'White' : 'Black';
		return mate === 0 ? `${winner} checkmates` : `${winner} mates in ${Math.abs(mate)}`;
	}
	return 'Unavailable';
}

export function weaknessLabel(key: string) {
	const [category, ...rest] = key.split(':');
	return rest.length ? (category === 'opening' ? 'ECO ' : '') + words(rest.join(':')) : words(key);
}
