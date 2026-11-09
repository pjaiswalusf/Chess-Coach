import type { Patterns, Weakness, Window } from '../src/lib/api/analytics.js';
import type { GameAnalysis, GameDetail, ReviewMove } from '../src/lib/api/review.js';

export const profile = 'a'.repeat(64);
export const reportHash = 'b'.repeat(64);
export const scriptText = '<script>globalThis.phase17Injected = true</script>';
export const game: GameDetail = {
	id: 17,
	played_at: '2026-01-09T14:00:00Z',
	opponent: 'White fixture',
	player_color: 'black',
	result: 'loss',
	time_class: 'rapid',
	opening_name: null,
	analysis_status: 'completed',
	white_username: 'White fixture',
	black_username: 'Black fixture',
	white_rating: 1800,
	black_rating: 1400,
	player_rating: 1400,
	critical_errors: 1,
	eco_code: null,
	time_control: '600+5',
	raw_pgn: '[Result "1-0"]\n\n38. a8=Q {' + scriptText + '} Kg6 1-0',
	completion_provenance: 'pgn_declaration'
};
const initial = '8/P6k/8/8/8/8/8/7K w - - 0 38';
const promoted = 'Q7/7k/8/8/8/8/8/7K b - - 0 38';
const first: ReviewMove = {
	evidence_kind: 'single_pass_estimate',
	game_id: 17,
	profile_hash: profile,
	ply: 1,
	move_number: 38,
	mover: 'white',
	played_move_san: 'a8=Q',
	played_move_uci: 'a7a8q',
	fen_before: initial,
	fen_after: promoted,
	best_move_uci: 'a7a8q',
	eval_before_cp_white: 10,
	eval_after_cp_white: 20,
	mate_before_white: null,
	mate_after_white: null,
	mate_before_winner: null,
	mate_after_winner: null,
	loss_cp: 0,
	severity: 'normal',
	pv_json: ['a7a8q']
};
export const gameAnalysis: GameAnalysis = {
	game_id: 17,
	profile_hash: profile,
	status: 'completed',
	initial_fen: initial,
	engine_version: 'Fixture engine',
	analysis_version: 'single-v1',
	moves: [
		first,
		{
			...first,
			ply: 2,
			mover: 'black',
			played_move_san: 'Kg6',
			played_move_uci: 'h7g6',
			fen_before: promoted,
			fen_after: 'Q7/8/6k1/8/8/8/8/7K w - - 1 39',
			best_move_uci: 'h7g7',
			pv_json: ['h7g7'],
			eval_before_cp_white: 20,
			eval_after_cp_white: 210,
			loss_cp: 190,
			severity: 'critical'
		}
	]
};
export const weakness: Weakness = {
	recency_weight: 1,
	candidate_key: 'phase:endgame',
	category: 'phase',
	opportunities: 120,
	distinct_games: 12,
	significant_errors: 3,
	critical_errors: 12,
	priority_score: 22.5,
	source_moves: [[17, 2]],
	evidence_status: 'sufficient'
};
export function patterns(window: Window, analyzed = 12): Patterns {
	return {
		status: analyzed === 12 ? 'COMPLETE' : 'PARTIAL',
		filters: { window, color: 'all', time_class: 'all' },
		profile_hash: profile,
		report_hash: reportHash,
		analytics_version: 'longitudinal-v1',
		policy_version: 'support-v1',
		ranker_version: 'weakness-ranker-v1',
		selected_game_ids: Array.from({ length: 12 }, (_, i) => i + 6),
		health: {
			integrity: 'PASS',
			database_integrity: true,
			foreign_keys: true,
			selected_games: 12,
			analyzed_games: analyzed,
			analysis_coverage: analyzed / 12,
			statuses: { done: analyzed },
			selected_player_moves: 120,
			analyzed_player_moves: analyzed * 10,
			move_evidence_coverage: analyzed / 12,
			clock_data_coverage: null,
			opening_data_coverage: null,
			errors: [],
			warnings: []
		},
		patterns: analyzed === 12 ? { phase: [weakness] } : {},
		contexts: [],
		conversion: null,
		conversion_strength: false,
		recent_trends: []
	};
}
export const noMoveCoaching = {
	status: 'not_generated',
	job_id: null,
	coach: null,
	evidence: { game_id: 17, ply: 2, profile_hash: profile }
};
export const noHistoricalCoaching = {
	status: 'not_generated',
	job_id: null,
	coach: null,
	evidence: { report_hash: reportHash }
};
