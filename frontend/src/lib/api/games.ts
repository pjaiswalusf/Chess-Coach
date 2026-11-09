import { apiRequest, invalidResponse, isRecord } from './client.js';
import type { components, paths } from './generated/schema.js';

export type GamePage =
	paths['/api/v1/games']['get']['responses'][200]['content']['application/json'];

export type GameItem = components['schemas']['GameItem'];
export type GameQuery = NonNullable<paths['/api/v1/games']['get']['parameters']['query']>;

function optionalCount(value: unknown) {
	return value == null || (typeof value === 'number' && Number.isSafeInteger(value) && value >= 0);
}

const results = ['win', 'loss', 'draw', 'unknown'];
export function isGame(game: unknown): game is GameItem {
	return (
		isRecord(game) &&
		typeof game.id === 'number' &&
		Number.isSafeInteger(game.id) &&
		game.id > 0 &&
		typeof game.opponent === 'string' &&
		typeof game.result === 'string' &&
		results.includes(game.result) &&
		typeof game.played_at === 'string' &&
		optionalCount(game.player_rating) &&
		optionalCount(game.critical_errors) &&
		(game.player_color === 'white' || game.player_color === 'black') &&
		typeof game.analysis_status === 'string' &&
		['pending', 'running', 'completed', 'failed', 'incompatible'].includes(game.analysis_status) &&
		[game.time_class, game.opening_name].every(
			(value) => value === null || typeof value === 'string'
		)
	);
}

export async function getGames(signal?: AbortSignal, query?: GameQuery): Promise<GamePage> {
	const params = new URLSearchParams();
	for (const [key, value] of Object.entries(query ?? {})) {
		if (value !== undefined && value !== null) params.set(key, String(value));
	}
	const data = await apiRequest<GamePage>(`/api/v1/games${params.size ? '?' + params : ''}`, {
		signal
	});
	if (
		!isRecord(data) ||
		!Array.isArray(data.items) ||
		!Number.isInteger(data.total) ||
		data.total < data.items.length ||
		!Number.isSafeInteger(data.offset) ||
		data.offset < 0 ||
		(query?.offset !== undefined && data.offset !== query.offset) ||
		!Number.isInteger(data.limit) ||
		data.limit < 1 ||
		data.items.length > data.limit ||
		(query?.limit !== undefined && data.limit !== query.limit) ||
		!data.items.every(isGame)
	) {
		throw invalidResponse();
	}
	return data;
}
