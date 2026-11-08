import { request } from './analysis';
import type { CoachingResponse } from './generated';

function path(game: number, ply: number, profile: string) {
	return `/games/${game}/moves/${ply}/explanation?profile_hash=${encodeURIComponent(profile)}`;
}

export const coachingApi = {
	get: (game: number, ply: number, profile: string) =>
		request<CoachingResponse>(path(game, ply, profile)),
	generate: (game: number, ply: number, profile: string) =>
		request<CoachingResponse>(path(game, ply, profile), 'POST'),
	job: (id: number) => request<CoachingResponse>(`/coaching-jobs/${id}`)
};
