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

type ComponentHealth =
	paths['/api/v1/system/health']['get']['responses'][200]['content']['application/json'];

export async function getComponentHealth(signal?: AbortSignal): Promise<ComponentHealth> {
	const data = await apiRequest<ComponentHealth>(
		'/api/v1/system/health',
		{ signal, cache: 'no-store' },
		8000,
		503
	);
	if (
		!isRecord(data) ||
		!['healthy', 'degraded', 'unavailable'].includes(data.overall) ||
		!isRecord(data.components) ||
		typeof data.checked_at !== 'string' ||
		Number.isNaN(Date.parse(data.checked_at)) ||
		!Object.values(data.components).every(
			(check) =>
				isRecord(check) &&
				['pass', 'warn', 'fail', 'skip'].includes(check.status) &&
				typeof check.message === 'string' &&
				typeof check.required === 'boolean' &&
				(check.action == null || typeof check.action === 'string')
		)
	) {
		throw invalidResponse();
	}
	return data;
}

type SystemMetrics =
	paths['/api/v1/system/metrics']['get']['responses'][200]['content']['application/json'];

export async function getSystemMetrics(signal?: AbortSignal): Promise<SystemMetrics> {
	const data = await apiRequest<SystemMetrics>('/api/v1/system/metrics', {
		signal,
		cache: 'no-store'
	});
	const measurement = (value: unknown) =>
		value === null || (typeof value === 'number' && Number.isFinite(value) && value >= 0);
	if (
		!isRecord(data) ||
		!isRecord(data.coaching) ||
		!Number.isInteger(data.coaching.window_days) ||
		!Number.isInteger(data.coaching.sample_count) ||
		!Number.isInteger(data.coaching.first_schema_sample_count) ||
		![
			data.coaching.latency_p50_ms,
			data.coaching.first_schema_failure_rate,
			data.coaching.final_failure_rate
		].every(measurement) ||
		(data.analysis !== null &&
			(!isRecord(data.analysis) ||
				typeof data.analysis.run_id !== 'string' ||
				![
					data.analysis.positions_per_second,
					data.analysis.cache_hit_rate,
					data.analysis.duration_ms,
					data.analysis.games_per_hour
				].every(measurement)))
	) {
		throw invalidResponse();
	}
	return data;
}
