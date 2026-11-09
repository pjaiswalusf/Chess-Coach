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
		(data.analysis_version !== undefined && typeof data.analysis_version !== 'string') ||
		(data.checked_at !== undefined &&
			(typeof data.checked_at !== 'string' || Number.isNaN(Date.parse(data.checked_at)))) ||
		![data.components.database, data.components.stockfish, data.components.ollama].every(
			(service) =>
				isRecord(service) &&
				serviceStates.includes(service.status) &&
				(service.model_status == null || serviceStates.includes(service.model_status)) &&
				[service.model, service.version].every(
					(value) => value == null || typeof value === 'string'
				)
		) ||
		(data.statistics !== null &&
			(!isRecord(data.statistics) ||
				![
					data.statistics.games_stored,
					data.statistics.games_analyzed,
					data.statistics.pending_games,
					...[
						data.statistics.positions_cached,
						data.statistics.active_sync_runs,
						data.statistics.active_analysis_runs,
						data.statistics.active_coaching_jobs
					].filter((n) => n !== undefined)
				].every((value) => Number.isInteger(value) && value >= 0)))
	) {
		throw invalidResponse();
	}
	return data;
}
