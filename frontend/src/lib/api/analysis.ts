import type { RunResponse, WorkerResponse, GameAnalysisResponse } from './generated';

export async function request<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
	const response = await fetch(`/api/v1${path}`, {
		method,
		headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
		body: body === undefined ? undefined : JSON.stringify(body)
	});
	if (!response.ok) {
		let message = `Request failed (${response.status}). Retry after checking the API.`;
		try {
			const error: { message?: string } = await response.json();
			message = error.message ?? message;
		} catch {
			// A disconnected proxy may return HTML rather than an API error.
		}
		throw new Error(message);
	}
	return response.json() as Promise<T>;
}

export const analysisApi = {
	status: () => request<WorkerResponse>('/analysis-worker'),
	runs: () => request<RunResponse[]>('/analysis-runs'),
	start: (player: number) =>
		request<RunResponse>('/analysis-runs', 'POST', { tracked_player_id: player }),
	cancel: (id: number) => request<RunResponse>(`/analysis-runs/${id}/cancel`, 'POST'),
	moves: (game: number, profile: string) =>
		request<GameAnalysisResponse>(
			`/games/${game}/analysis?profile_hash=${encodeURIComponent(profile)}`
		).then((result) => result.moves)
};
