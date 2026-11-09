import { apiRequest, invalidResponse, isRecord } from './client.js';
import { ApiError } from './errors.js';
import type { components } from './generated/schema.js';

export type Overview = components['schemas']['OverviewResponse'];
export type Patterns = components['schemas']['PatternsResponse'];
export type Window = NonNullable<components['schemas']['AnalyticsFilters']['window']>;
export type Weakness = components['schemas']['Weakness'];

const isCount = (n: unknown) => typeof n === 'number' && Number.isSafeInteger(n) && n >= 0;
const isRate = (r: unknown) =>
	isRecord(r) &&
	isCount(r.numerator) &&
	isCount(r.denominator) &&
	(r.per_100 === null || (typeof r.per_100 === 'number' && Number.isFinite(r.per_100)));

function isWeakness(row: unknown) {
	return (
		isRecord(row) &&
		typeof row.candidate_key === 'string' &&
		[row.opportunities, row.distinct_games, row.significant_errors, row.critical_errors].every(
			isCount
		) &&
		Array.isArray(row.source_moves) &&
		row.source_moves.every(
			(ref) => Array.isArray(ref) && ref.length === 2 && ref.every((id) => isCount(id) && id > 0)
		)
	);
}

function isPeriod(period: unknown) {
	return (
		isRecord(period) &&
		Array.isArray(period.game_ids) &&
		typeof period.first_game_at === 'string' &&
		typeof period.last_game_at === 'string' &&
		isRate(period.critical)
	);
}

function isMoveMetrics(moves: unknown) {
	return (
		isRecord(moves) &&
		isRate(moves.significant) &&
		isCount(moves.comparable_moves) &&
		(moves.mean_loss_cp === null ||
			(typeof moves.mean_loss_cp === 'number' && Number.isFinite(moves.mean_loss_cp)))
	);
}

async function getReport<T extends Overview | Patterns>(path: string, signal?: AbortSignal) {
	const data = await apiRequest<T>(path, { signal }, 30000);
	if (
		!isRecord(data) ||
		!['NO_GAMES', 'DATA_ERROR', 'COMPLETE', 'PARTIAL', 'INSUFFICIENT_DATA'].includes(data.status)
	)
		throw invalidResponse();
	if (data.status === 'DATA_ERROR')
		throw new ApiError(
			'invalid_response',
			'The stored evidence did not pass the backend’s integrity checks. Check System and retry.'
		);
	if (
		!isRecord(data.filters) ||
		!isRecord(data.patterns) ||
		!Object.values(data.patterns).every((rows) => Array.isArray(rows) && rows.every(isWeakness)) ||
		(data.status !== 'NO_GAMES' &&
			(!isRecord(data.health) ||
				![
					data.health.selected_games,
					data.health.analyzed_games,
					data.health.analyzed_player_moves
				].every(isCount))) ||
		typeof data.conversion_strength !== 'boolean' ||
		(data.conversion_strength && (!isRecord(data.conversion) || !isRate(data.conversion.wins))) ||
		!Array.isArray(data.recent_trends) ||
		!data.recent_trends.every(
			(trend) =>
				isRecord(trend) &&
				[trend.time_class, trend.color, trend.time_control, trend.direction].every(
					(value) => typeof value === 'string'
				) &&
				isPeriod(trend.earlier) &&
				isPeriod(trend.recent)
		)
	)
		throw invalidResponse();
	return data;
}

export async function getOverview(signal?: AbortSignal) {
	const report = await getReport<Overview>('/api/v1/analytics/overview?window=last_50', signal);
	if (
		!Array.isArray(report.phases) ||
		!report.phases.every(
			(segment) =>
				isRecord(segment) &&
				typeof segment.key === 'string' &&
				isRecord(segment.summary) &&
				isMoveMetrics(segment.summary.moves)
		) ||
		!Array.isArray(report.openings) ||
		!report.openings.every(
			(segment) =>
				isRecord(segment) &&
				typeof segment.key === 'string' &&
				Array.isArray(segment.opening_names) &&
				segment.opening_names.every((name) => typeof name === 'string')
		) ||
		(report.metrics !== null && (!isRecord(report.metrics) || !isMoveMetrics(report.metrics.moves)))
	)
		throw invalidResponse();
	return report;
}

export async function getPatterns(window: Window, signal?: AbortSignal) {
	const report = await getReport<Patterns>(`/api/v1/analytics/patterns?window=${window}`, signal);
	if (report.filters.window !== window) throw invalidResponse();
	return report;
}
