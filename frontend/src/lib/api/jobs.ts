import { apiRequest, invalidResponse, isRecord } from './client.js';
import type { components } from './generated/schema.js';

type Schemas = components['schemas'];
export type SyncRun = Schemas['SyncRunResponse'];
export type AnalysisProgress = Schemas['RunProgressResponse'];

const positiveId = (value: unknown) =>
	typeof value === 'number' && Number.isSafeInteger(value) && value > 0;
const count = (value: unknown) =>
	typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
const states = ['queued', 'running', 'completed', 'failed'];

export const isActive = (status?: string) => status === 'queued' || status === 'running';

function json(method: string, body: object, signal: AbortSignal): RequestInit {
	return {
		method,
		body: JSON.stringify(body),
		headers: { 'Content-Type': 'application/json' },
		signal
	};
}

function accepted<T extends Schemas['AcceptedRun']>(data: T): T {
	if (!isRecord(data) || !positiveId(data.run_id) || !states.includes(data.status))
		throw invalidResponse();
	return data;
}

export const jobsApi = {
	async player(signal: AbortSignal) {
		const data = await apiRequest<Schemas['PlayerResponse']>('/api/v1/player', { signal });
		if (
			!isRecord(data) ||
			typeof data.configured !== 'boolean' ||
			(data.configured
				? !isRecord(data.player) ||
					!positiveId(data.player.id) ||
					typeof data.player.username !== 'string'
				: data.player !== null)
		)
			throw invalidResponse();
		return data.player;
	},
	setPlayer: (username: string, signal: AbortSignal) =>
		apiRequest<Schemas['PlayerResponse']>(
			'/api/v1/player',
			json('PUT', { username, verify: true }, signal)
		),
	async latest(signal: AbortSignal) {
		const data = await apiRequest<Schemas['LatestRuns']>('/api/v1/sync-runs/latest-work', {
			signal
		});
		if (
			!isRecord(data) ||
			![data.sync_run_id, data.analysis_run_id].every((id) => id === null || positiveId(id))
		)
			throw invalidResponse();
		return data;
	},
	startSync: (signal: AbortSignal) =>
		apiRequest<Schemas['AcceptedRun']>('/api/v1/sync-runs', json('POST', {}, signal)).then(
			accepted
		),
	startAnalysis: (signal: AbortSignal) =>
		apiRequest<Schemas['RunResponse']>(
			'/api/v1/analysis-runs',
			json('POST', { scope: 'pending' }, signal)
		).then(accepted),
	async sync(id: number, signal: AbortSignal) {
		const data = accepted(await apiRequest<SyncRun>(`/api/v1/sync-runs/${id}`, { signal }));
		if (
			data.run_id !== id ||
			!isRecord(data.progress) ||
			![
				data.progress.archives_processed,
				data.progress.games_seen,
				data.progress.games_inserted,
				data.progress.games_existing,
				data.progress.games_failed,
				data.progress.games_skipped
			].every(count) ||
			!(data.progress.archives_total === null || count(data.progress.archives_total))
		)
			throw invalidResponse();
		return data;
	},
	async analysis(id: number, signal: AbortSignal) {
		const data = accepted(
			await apiRequest<AnalysisProgress>(`/api/v1/analysis-runs/${id}/progress`, { signal })
		);
		if (
			data.run_id !== id ||
			![
				data.games_total,
				data.games_completed,
				data.games_failed,
				data.games_skipped,
				data.games_excluded,
				data.games_remaining
			].every(count)
		)
			throw invalidResponse();
		return data;
	}
};
