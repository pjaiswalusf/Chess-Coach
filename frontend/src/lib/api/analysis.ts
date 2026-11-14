import { apiRequest, invalidResponse, isRecord, jsonRequest } from './client.js';
import type { components, paths } from './generated/schema.js';

export type RunResponse = components['schemas']['RunResponse'];
export type WorkerResponse = components['schemas']['WorkerResponse'];
export type MoveResponse = Omit<components['schemas']['ReviewMove'], 'fen_after' | 'severity'>;
type GameAnalysis = components['schemas']['GameAnalysisResponse'];
type StartRun =
	paths['/api/v1/analysis-runs']['post']['requestBody']['content']['application/json'];

function isRun(run: unknown): run is RunResponse {
	return (
		isRecord(run) &&
		Number.isInteger(run.id) &&
		typeof run.status === 'string' &&
		isRecord(run.engine_config_json) &&
		Array.isArray(run.games) &&
		run.games.every(
			(game) => isRecord(game) && Number.isInteger(game.game_id) && typeof game.status === 'string'
		)
	);
}

function requireRun(run: unknown): RunResponse {
	if (!isRun(run)) throw invalidResponse();
	return run;
}

export const analysisApi = {
	async status(signal?: AbortSignal) {
		const worker = await apiRequest<WorkerResponse>('/api/v1/analysis-worker', { signal });
		if (
			!isRecord(worker) ||
			!Array.isArray(worker.players) ||
			!worker.players.every(
				(player) =>
					isRecord(player) && Number.isInteger(player.id) && typeof player.username === 'string'
			)
		) {
			throw invalidResponse();
		}
		return worker;
	},
	async runs(signal?: AbortSignal) {
		const runs = await apiRequest<unknown>('/api/v1/analysis-runs', { signal });
		if (!Array.isArray(runs) || !runs.every(isRun)) throw invalidResponse();
		return runs;
	},
	start: (player: number, signal?: AbortSignal) =>
		apiRequest<unknown>(
			'/api/v1/analysis-runs',
			jsonRequest(
				'POST',
				{ scope: 'pending', tracked_player_id: player } satisfies StartRun,
				signal
			)
		).then(requireRun),
	cancel: (id: number, signal?: AbortSignal) =>
		apiRequest<unknown>(`/api/v1/analysis-runs/${id}/cancel`, { method: 'POST', signal }).then(
			requireRun
		),
	async moves(game: number, profile: string, signal?: AbortSignal) {
		const analysis = await apiRequest<GameAnalysis>(
			`/api/v1/games/${game}/analysis?profile_hash=${encodeURIComponent(profile)}`,
			{ signal }
		);
		if (
			!isRecord(analysis) ||
			!Array.isArray(analysis.moves) ||
			!analysis.moves.every(
				(move) =>
					isRecord(move) && Number.isInteger(move.ply) && typeof move.played_move_san === 'string'
			)
		) {
			throw invalidResponse();
		}
		return analysis.moves;
	}
};
