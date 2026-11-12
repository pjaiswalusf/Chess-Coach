import { apiRequest, invalidResponse, isRecord } from './client.js';
import { isGame } from './games.js';
import type { components } from './generated/schema.js';

type Schemas = components['schemas'];
export type ReviewMove = Schemas['ReviewMove'];
export type ReviewRating = Schemas['ReviewRating'];
export type GameAnalysis = Schemas['GameAnalysisResponse'];
export type GameDetail = Schemas['GameDetail'];
export type VariationPosition = Schemas['ReviewVariationResponse'];
export type VariationEvaluation = Schemas['ReviewVariationEvaluation'];

export const isProfile = (value: unknown): value is string =>
	typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);

export async function getGame(id: number, signal: AbortSignal) {
	const data = await apiRequest<GameDetail>(`/api/v1/games/${id}`, { signal });
	if (
		!isGame(data) ||
		data.id !== id ||
		![data.white_username, data.black_username, data.raw_pgn].every(
			(value) => typeof value === 'string'
		) ||
		![data.white_rating, data.black_rating].every(
			(value) => value === null || Number.isSafeInteger(value)
		) ||
		![data.time_control, data.eco_code].every(
			(value) => value === null || typeof value === 'string'
		) ||
		!['chesscom_archive', 'pgn_declaration'].includes(data.completion_provenance)
	)
		throw invalidResponse();
	return data;
}

const score = (cp: unknown, mate: unknown, winner: unknown) =>
	(Number.isSafeInteger(cp) && mate === null && winner === null) ||
	(cp === null && Number.isSafeInteger(mate) && typeof winner === 'boolean') ||
	(cp === null && mate === null && winner === null);

function validMove(move: ReviewMove, id: number, ply: number, profile: string, before: string) {
	return (
		isRecord(move) &&
		move.game_id === id &&
		move.ply === ply &&
		move.profile_hash === profile &&
		Number.isSafeInteger(move.move_number) &&
		move.move_number > 0 &&
		(move.mover === 'white' || move.mover === 'black') &&
		move.fen_before === before &&
		typeof move.fen_after === 'string' &&
		typeof move.played_move_uci === 'string' &&
		typeof move.played_move_san === 'string' &&
		typeof move.pv_san === 'string' &&
		(move.best_move_uci === null || typeof move.best_move_uci === 'string') &&
		Array.isArray(move.pv_json) &&
		move.pv_json.every((uci) => typeof uci === 'string') &&
		[
			'brilliant',
			'great',
			'best',
			'book',
			'excellent',
			'good',
			'inaccuracy',
			'mistake',
			'miss',
			'blunder'
		].includes(move.rating) &&
		(move.loss_cp === null || (Number.isSafeInteger(move.loss_cp) && move.loss_cp >= 0)) &&
		(move.severity === null ||
			['normal', 'minor', 'significant', 'critical'].includes(move.severity)) &&
		score(move.eval_before_cp_white, move.mate_before_white, move.mate_before_winner) &&
		score(move.eval_after_cp_white, move.mate_after_white, move.mate_after_winner)
	);
}

export async function getGameAnalysis(id: number, profile: string | null, signal: AbortSignal) {
	const query = profile === null ? '' : `?profile_hash=${profile}`;
	const data = await apiRequest<GameAnalysis>(`/api/v1/games/${id}/analysis${query}`, { signal });
	if (
		!isRecord(data) ||
		data.game_id !== id ||
		!Array.isArray(data.moves) ||
		!Array.isArray(data.legal_moves_by_ply) ||
		!['pending', 'running', 'completed', 'failed', 'incompatible'].includes(data.status) ||
		(profile !== null && data.profile_hash !== profile)
	)
		throw invalidResponse();

	if (data.status !== 'completed') {
		if (data.moves.length || data.legal_moves_by_ply.length) throw invalidResponse();
		return data;
	}
	if (
		!isProfile(data.profile_hash) ||
		typeof data.initial_fen !== 'string' ||
		typeof data.engine_version !== 'string' ||
		typeof data.analysis_version !== 'string' ||
		data.legal_moves_by_ply.length !== data.moves.length + 1 ||
		!data.legal_moves_by_ply.every(
			(moves) => Array.isArray(moves) && moves.every((move) => typeof move === 'string')
		)
	)
		throw invalidResponse();
	let before = data.initial_fen;
	for (const [index, move] of data.moves.entries()) {
		if (!validMove(move, id, index + 1, data.profile_hash, before)) throw invalidResponse();
		before = move.fen_after;
	}
	return data;
}

export async function getVariationPosition(
	id: number,
	body: Schemas['ReviewVariationRequest'],
	signal: AbortSignal
) {
	const data = await apiRequest<VariationPosition>(`/api/v1/games/${id}/review/variation`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body),
		signal
	});
	if (
		!isRecord(data) ||
		typeof data.fen !== 'string' ||
		!['white', 'black'].includes(data.side_to_move) ||
		!Array.isArray(data.legal_moves) ||
		!data.legal_moves.every((move) => typeof move === 'string') ||
		(body.line.length ? typeof data.san !== 'string' : data.san !== null) ||
		(data.outcome !== null && !['1-0', '0-1', '1/2-1/2'].includes(data.outcome))
	)
		throw invalidResponse();
	const evaluation = data.evaluation;
	if (evaluation === null) {
		if (body.evaluate || data.outcome !== null) throw invalidResponse();
	} else if (
		!isRecord(evaluation) ||
		!score(evaluation.cp, evaluation.mate, evaluation.white_wins) ||
		(evaluation.cp === null && evaluation.mate === null) ||
		typeof evaluation.continuation !== 'string' ||
		(evaluation.engine !== null && typeof evaluation.engine !== 'string') ||
		(evaluation.best_move !== null && !data.legal_moves.includes(evaluation.best_move))
	)
		throw invalidResponse();
	return data;
}
