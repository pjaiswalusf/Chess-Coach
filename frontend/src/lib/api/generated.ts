// Generated from FastAPI OpenAPI by scripts/generate_api_types.py. Do not edit.
export type AnalysisRunStatus =
	'pending' | 'running' | 'done' | 'completed_with_errors' | 'failed' | 'cancelled';

export type CreateRun = {
	tracked_player_id: number;
};

export type DependencyStatus = {
	state: 'available' | 'unavailable' | 'unknown';
	detail?: string | null;
};

export type HTTPValidationError = {
	detail?: Array<ValidationError>;
};

export type MoveResponse = {
	game_id: number;
	profile_hash: string;
	ply: number;
	move_number: number;
	mover: string;
	played_move_uci: string;
	played_move_san: string;
	fen_before: string;
	best_move_uci: string | null;
	eval_before_cp_white: number | null;
	eval_after_cp_white: number | null;
	mate_before_white: number | null;
	mate_after_white: number | null;
	mate_before_winner: boolean | null;
	mate_after_winner: boolean | null;
	loss_cp: number | null;
	pv_json: Array<string>;
	evidence_kind?: string;
};

export type Player = {
	id: number;
	username: string;
};

export type RunGame = {
	game_id: number;
	status: string;
	attempt_count: number;
	error_code: string | null;
};

export type RunResponse = {
	id: number;
	tracked_player_id: number;
	status: AnalysisRunStatus;
	created_at: string;
	started_at: string | null;
	finished_at: string | null;
	last_heartbeat_at: string | null;
	profile_hash: string;
	engine_version: string;
	analysis_version: string;
	engine_config_json: Record<string, number | number | string>;
	draw_policy_version: string;
	games_total: number;
	games_completed: number;
	games_failed: number;
	games_skipped: number;
	games_excluded: number;
	positions_analyzed: number;
	terminal_positions: number;
	cache_hits: number;
	cache_misses: number;
	engine_seconds: number;
	cancel_requested: boolean;
	error_code: string | null;
	error_message: string | null;
	progress_percent: number;
	successful_percent: number;
	worker_available: boolean;
	games: Array<RunGame>;
};

export type SystemStatusResponse = {
	api: DependencyStatus;
	stockfish: DependencyStatus;
	ollama: DependencyStatus;
	ollama_model: DependencyStatus;
};

export type ValidationError = {
	loc: Array<string | number>;
	msg: string;
	type: string;
	input?: unknown;
	ctx?: Record<string, unknown>;
};

export type WorkerResponse = {
	available: boolean;
	engine_version: string | null;
	heartbeat_at: string | null;
	database: string;
	players: Array<Player>;
};
