import { apiRequest } from './client.js';
import type { components } from './generated/schema.js';

export type PublicPuzzle = components['schemas']['PublicPuzzle'];
export type AttemptResult = components['schemas']['AttemptResult'];
export type TrainingStats = components['schemas']['TrainingStats'];
export type TransferReport = components['schemas']['TransferReport'];
export type SubmitAttempt = components['schemas']['SubmitAttempt'];
export type PlayPuzzle = components['schemas']['PlayPuzzle'];

const prefix = '/api/v1/training';

export function getNextPuzzle(signal?: AbortSignal, puzzleId?: string) {
	const query = puzzleId ? '?' + new URLSearchParams({ puzzle_id: puzzleId }) : '';
	return apiRequest<components['schemas']['NextPuzzle']>(prefix + '/next' + query, {
		signal,
		cache: 'no-store'
	});
}

export function submitPuzzleAttempt(id: number, attempt: SubmitAttempt) {
	return apiRequest<AttemptResult>(prefix + '/' + id + '/attempts', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(attempt)
	});
}

export function playPuzzle(id: number, attempt: PlayPuzzle) {
	return apiRequest<components['schemas']['PuzzleStep']>(prefix + '/' + id + '/play', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(attempt)
	});
}

export function getTrainingStats(signal?: AbortSignal) {
	return apiRequest<TrainingStats>(prefix + '/stats', { signal, cache: 'no-store' });
}

export function getTrainingProgress(signal?: AbortSignal) {
	return apiRequest<TransferReport>(prefix + '/progress', { signal, cache: 'no-store' });
}
