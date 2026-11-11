import { apiRequest, invalidResponse, isRecord } from './client.js';
import type { Window } from './analytics.js';
import type { components } from './generated/schema.js';

export type LLMHealth = components['schemas']['LLMHealth'];
export type CoachingResponse = components['schemas']['CoachingResponse'];

function path(game: number, ply: number, profile: string) {
	return `/api/v1/games/${game}/moves/${ply}/explanation?profile_hash=${encodeURIComponent(profile)}`;
}

async function readCoaching(path: string, init: RequestInit): Promise<CoachingResponse> {
	const data = await apiRequest<CoachingResponse>(path, init);
	if (
		!isRecord(data) ||
		typeof data.status !== 'string' ||
		(data.game_review !== undefined &&
			(!Array.isArray(data.game_review) ||
				data.game_review.some(
					(moment) =>
						!isRecord(moment) ||
						!Number.isSafeInteger(moment.ply) ||
						moment.ply < 1 ||
						typeof moment.move !== 'string' ||
						typeof moment.played_fact !== 'string' ||
						(moment.alternative_fact !== null && typeof moment.alternative_fact !== 'string') ||
						(moment.practice_tip != null && typeof moment.practice_tip !== 'string')
				))) ||
		(data.coach != null && (!isRecord(data.coach) || typeof data.coach.summary !== 'string'))
	) {
		throw invalidResponse();
	}
	return data;
}

export async function getLLMHealth(signal: AbortSignal) {
	const data = await apiRequest<LLMHealth>('/api/v1/system/llm', { signal, cache: 'no-store' });
	if (
		!isRecord(data) ||
		!['ready', 'server_unavailable', 'model_missing', 'check_failed'].includes(data.status) ||
		typeof data.model !== 'string'
	)
		throw invalidResponse();
	return data;
}

export const coachingApi = {
	game: (game: number, profile: string, signal: AbortSignal, generate = false) =>
		readCoaching(`/api/v1/games/${game}/coaching?profile_hash=${encodeURIComponent(profile)}`, {
			method: generate ? 'POST' : 'GET',
			signal
		}),
	history: (window: Window, profile: string, signal: AbortSignal, expectedHash?: string) =>
		readCoaching(
			`/api/v1/coaching/history?window=${window}&profile_hash=${encodeURIComponent(profile)}${expectedHash ? '&expected_report_hash=' + encodeURIComponent(expectedHash) : ''}`,
			{ method: expectedHash ? 'POST' : 'GET', signal }
		),
	get: (game: number, ply: number, profile: string, signal?: AbortSignal) =>
		readCoaching(path(game, ply, profile), { method: 'GET', signal }),
	generate: (game: number, ply: number, profile: string, signal?: AbortSignal) =>
		readCoaching(path(game, ply, profile), { method: 'POST', signal }),
	job: (id: number, signal?: AbortSignal) => readCoaching(`/api/v1/coaching-jobs/${id}`, { signal })
};
