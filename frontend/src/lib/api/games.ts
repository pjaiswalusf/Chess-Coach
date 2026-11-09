import { apiRequest, invalidResponse, isRecord } from './client.js';
import type { paths } from './generated/schema.js';

export type GamePage =
	paths['/api/v1/games']['get']['responses'][200]['content']['application/json'];

const results = ['win', 'loss', 'draw', 'unknown'];

export async function getGames(signal?: AbortSignal): Promise<GamePage> {
	const data = await apiRequest<GamePage>('/api/v1/games', { signal });
	if (
		!isRecord(data) ||
		!Array.isArray(data.items) ||
		!Number.isInteger(data.total) ||
		data.total < data.items.length ||
		(data.items.length === 0 && data.total !== 0) ||
		!data.items.every(
			(game) =>
				isRecord(game) &&
				Number.isInteger(game.id) &&
				typeof game.opponent === 'string' &&
				results.includes(game.result)
		)
	) {
		throw invalidResponse();
	}
	return data;
}
