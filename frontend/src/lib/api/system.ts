import { apiRequest, invalidResponse, isRecord } from './client.js';
import type { paths } from './generated/schema.js';

export type SystemReport =
	paths['/api/v1/system']['get']['responses'][200]['content']['application/json'];

const serviceStates = ['available', 'unavailable', 'unknown'];

export async function getSystem(signal?: AbortSignal): Promise<SystemReport> {
	const data = await apiRequest<SystemReport>('/api/v1/system', { signal, cache: 'no-store' });
	if (
		!isRecord(data) ||
		!['healthy', 'degraded', 'unavailable'].includes(data.status) ||
		!isRecord(data.components) ||
		![data.components.database, data.components.stockfish, data.components.ollama].every(
			(service) => isRecord(service) && serviceStates.includes(service.status)
		) ||
		(data.statistics !== null &&
			(!isRecord(data.statistics) ||
				![
					data.statistics.games_stored,
					data.statistics.games_analyzed,
					data.statistics.pending_games
				].every((value) => Number.isInteger(value) && value >= 0)))
	) {
		throw invalidResponse();
	}
	return data;
}
