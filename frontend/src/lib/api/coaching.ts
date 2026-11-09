import { apiRequest, invalidResponse, isRecord } from './client.js';
import type { components } from './generated/schema.js';

export type CoachingResponse = components['schemas']['CoachingResponse'];

function path(game: number, ply: number, profile: string) {
	return `/api/v1/games/${game}/moves/${ply}/explanation?profile_hash=${encodeURIComponent(profile)}`;
}

async function readCoaching(path: string, init: RequestInit): Promise<CoachingResponse> {
	const data = await apiRequest<CoachingResponse>(path, init);
	if (
		!isRecord(data) ||
		typeof data.status !== 'string' ||
		(data.coach != null && (!isRecord(data.coach) || typeof data.coach.summary !== 'string'))
	) {
		throw invalidResponse();
	}
	return data;
}

export const coachingApi = {
	get: (game: number, ply: number, profile: string, signal?: AbortSignal) =>
		readCoaching(path(game, ply, profile), { method: 'GET', signal }),
	generate: (game: number, ply: number, profile: string, signal?: AbortSignal) =>
		readCoaching(path(game, ply, profile), { method: 'POST', signal }),
	job: (id: number, signal?: AbortSignal) => readCoaching(`/api/v1/coaching-jobs/${id}`, { signal })
};
