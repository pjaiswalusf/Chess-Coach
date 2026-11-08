// Generated from FastAPI OpenAPI by scripts/generate_api_types.py. Do not edit.
export type AcceptedRun = {
	run_id: number;
	status: 'queued' | 'running' | 'completed' | 'failed';
};

export type AnalysisRunStatus =
	'pending' | 'running' | 'done' | 'completed_with_errors' | 'failed' | 'cancelled';

export type AnalyticsFilters = {
	window?: 'last_20' | 'last_50' | 'last_100' | 'all';
	color?: 'white' | 'black' | 'all';
	time_class?: 'bullet' | 'blitz' | 'rapid' | 'daily' | 'all';
	profile_hash?: string | null;
};

export type AnalyticsHealthReport = {
	integrity: 'PASS' | 'FAIL';
	database_integrity: boolean;
	foreign_keys: boolean;
	selected_games: number;
	analyzed_games: number;
	analysis_coverage: number | null;
	statuses: Record<string, number>;
	selected_player_moves: number;
	analyzed_player_moves: number;
	move_evidence_coverage: number | null;
	clock_data_coverage: number | null;
	opening_data_coverage: number | null;
	errors: Array<Diagnostic>;
	warnings: Array<Diagnostic>;
};

export type CoachingResponse = {
	job_id?: number | null;
	status: string;
	evidence: MoveCoachingEvidence | HistoricalEvidence;
	coach?: MoveExplanation | HistoricalExplanation | null;
	error_code?: string | null;
	message?: string | null;
	cached?: boolean;
	model_digest?: string | null;
	attempt_count?: number;
};

export type Component = {
	status: 'available' | 'unavailable' | 'unknown';
	model?: string | null;
	version?: string | null;
};

export type Components = {
	database: Component;
	stockfish: Component;
	ollama: Component;
};

export type ContextMetric = {
	key: string;
	opportunities: MoveMetrics;
	comparison: MoveMetrics;
	unknown_moves: number;
	evidence_status: EvidenceStatus;
	strata: Record<string, MoveMetrics>;
};

export type CreateRun = {
	tracked_player_id?: number | null;
	scope?: 'pending';
};

export type DependencyStatus = {
	state: 'available' | 'unavailable' | 'unknown';
	detail?: string | null;
};

export type Diagnostic = {
	code: string;
	game_id?: number | null;
};

export type EngineScore = {
	cp_white?: number | null;
	mate_white?: number | null;
	mate_winner?: boolean | null;
};

export type ErrorResponse = {
	code: string;
	message: string;
	details?: Record<string, string>;
};

export type EvidenceStatus = 'sufficient' | 'insufficient' | 'unavailable';

export type GameAnalysisResponse = {
	game_id: number;
	status: 'pending' | 'running' | 'completed' | 'failed' | 'incompatible';
	profile_hash: string | null;
	engine_version: string | null;
	analysis_version: string | null;
	moves: Array<MoveResponse>;
};

export type GameDetail = {
	id: number;
	played_at: string;
	opponent: string;
	player_color: PlayerColor;
	result: GameResult;
	time_class: string | null;
	opening_name: string | null;
	analysis_status: 'pending' | 'running' | 'completed' | 'failed' | 'incompatible';
	white_username: string;
	black_username: string;
	white_rating: number | null;
	black_rating: number | null;
	eco_code: string | null;
	time_control: string | null;
	raw_pgn: string;
	completion_provenance: 'chesscom_archive' | 'pgn_declaration';
};

export type GameItem = {
	id: number;
	played_at: string;
	opponent: string;
	player_color: PlayerColor;
	result: GameResult;
	time_class: string | null;
	opening_name: string | null;
	analysis_status: 'pending' | 'running' | 'completed' | 'failed' | 'incompatible';
};

export type GamePage = {
	items: Array<GameItem>;
	total: number;
	limit: number;
	offset: number;
};

export type GamePhase = 'opening' | 'middlegame' | 'endgame' | 'unclassified';

export type GameResult = 'win' | 'loss' | 'draw' | 'unknown';

export type HealthResponse = {
	status?: 'ok';
};

export type HistoricalAdvice = {
	pattern_id: string;
	explanation: string;
	practice_tip: string;
};

export type HistoricalEvidence = {
	schema_version?: string;
	report_hash: string;
	analytics_version: string;
	policy_version: string;
	ranker_version: string;
	request: Record<string, unknown>;
	total_games: number;
	patterns: Array<Weakness>;
};

export type HistoricalExplanation = {
	status: 'explained' | 'insufficient_evidence';
	summary: string;
	priorities?: Array<HistoricalAdvice>;
};

export type LLMHealth = {
	status: 'ready' | 'server_unavailable' | 'model_missing' | 'check_failed';
	server_reachable: boolean;
	model_installed: boolean;
	model: string;
	model_digest?: string | null;
	message: string;
};

export type MoveCoachingEvidence = {
	schema_version?: 'move-evidence-v1';
	game_id: number;
	ply: number;
	player_color: PlayerColor;
	player_rating?: number | null;
	phase: GamePhase;
	fen_before: string;
	initial_fen: string;
	history_uci: Array<string>;
	history_before_start_unknown: boolean;
	played_move_uci: string;
	best_move_uci: string;
	best_line_uci: Array<string>;
	played_refutation_uci: Array<string>;
	before: EngineScore;
	after: EngineScore;
	loss_cp?: number | null;
	historical_theme_frequency?: number | null;
	completion_provenance: 'pgn_declaration' | 'chesscom_archive';
	source_hash: string;
	profile_hash: string;
	engine_version: string;
	analysis_version: string;
	draw_policy: string;
	feature_version: number;
};

export type MoveExplanation = {
	status: 'explained' | 'insufficient_evidence';
	summary: string;
	what_went_wrong?: string;
	why_best_move_works?: string;
	lesson?: string;
	practice_tip?: string;
};

export type MoveMetrics = {
	player_moves: number;
	games_represented: number;
	comparable_moves: number;
	excluded_losses: number;
	classifiable_moves: number;
	total_loss_cp: number;
	mean_loss_cp: number | null;
	median_loss_cp: number | null;
	significant: Rate;
	critical: Rate;
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

export type PatternsResponse = {
	filters: AnalyticsFilters;
	profile_hash: string | null;
	status: ReportStatus;
	analytics_version?: string;
	policy_version?: string;
	selected_game_ids: Array<number>;
	health: AnalyticsHealthReport | null;
	ranker_version?: string;
	patterns: Record<string, Array<Weakness>>;
	contexts: Array<ContextMetric>;
};

export type PlayerColor = 'white' | 'black';

export type PlayerInput = {
	platform?: 'chess.com';
	username: string;
};

export type PlayerResponse = {
	configured: boolean;
	player: chess_coach__api__schemas__contracts__Player | null;
};

export type Rate = {
	numerator: number;
	denominator: number;
	per_100: number | null;
};

export type ReportStatus = 'COMPLETE' | 'PARTIAL' | 'INSUFFICIENT_DATA' | 'DATA_ERROR' | 'NO_GAMES';

export type RunGame = {
	game_id: number;
	status: string;
	attempt_count: number;
	error_code: string | null;
};

export type RunResponse = {
	id: number;
	tracked_player_id: number;
	run_id: number;
	status: 'queued' | 'running' | 'completed' | 'failed';
	storage_status: AnalysisRunStatus;
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

export type Segment = {
	key: string;
	summary: Summary;
	evidence_status: EvidenceStatus;
	time_class_games: Record<string, number>;
	color_games: Record<string, number>;
	opening_names?: Array<string>;
	opening_family?: string | null;
	opening_moves?: MoveMetrics | null;
	early_errors?: Rate | null;
	median_first_error_move?: number | null;
};

export type SegmentsResponse = {
	filters: AnalyticsFilters;
	profile_hash: string | null;
	status: ReportStatus;
	analytics_version?: string;
	policy_version?: string;
	selected_game_ids: Array<number>;
	health: AnalyticsHealthReport | null;
	items: Array<Segment>;
};

export type Statistics = {
	games_stored: number;
	games_analyzed: number;
	pending_games: number;
};

export type Summary = {
	games_played: number;
	wins: number;
	draws: number;
	losses: number;
	score_percentage: number | null;
	win_rate: Rate;
	moves: MoveMetrics;
};

export type SummaryResponse = {
	filters: AnalyticsFilters;
	profile_hash: string | null;
	status: ReportStatus;
	analytics_version?: string;
	policy_version?: string;
	selected_game_ids: Array<number>;
	health: AnalyticsHealthReport | null;
	metrics: Summary | null;
};

export type SyncInput = Record<string, never>;

export type SyncProgress = {
	archives_total: number | null;
	archives_processed: number;
	games_seen: number;
	games_inserted: number;
	games_existing: number;
	games_failed: number;
};

export type SyncRunResponse = {
	run_id: number;
	status: 'queued' | 'running' | 'completed' | 'failed';
	started_at: string | null;
	finished_at: string | null;
	progress: SyncProgress;
	error: ErrorResponse | null;
	recoverable: boolean;
};

export type SystemResponse = {
	status: 'healthy' | 'degraded' | 'unavailable';
	components: Components;
	statistics: Statistics | null;
	checked_at: string;
};

export type SystemStatusResponse = {
	api: DependencyStatus;
	stockfish: DependencyStatus;
	ollama: DependencyStatus;
	ollama_model: DependencyStatus;
};

export type Weakness = {
	candidate_key: string;
	category: 'phase' | 'opening' | 'context';
	opportunities: number;
	significant_errors: number;
	critical_errors: number;
	distinct_games: number;
	priority_score: number;
	recency_weight?: number;
	evidence_status?: 'sufficient';
	source_moves: Array<[number, number]>;
};

export type WorkerResponse = {
	available: boolean;
	engine_version: string | null;
	heartbeat_at: string | null;
	database: string;
	players: Array<chess_coach__api__schemas__analysis__Player>;
};

export type chess_coach__api__schemas__analysis__Player = {
	id: number;
	username: string;
};

export type chess_coach__api__schemas__contracts__Player = {
	id: number;
	platform: 'chess.com';
	username: string;
};
