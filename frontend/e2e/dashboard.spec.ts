import { expect, test } from '@playwright/test';
import type { Overview } from '../src/lib/api/analytics.js';

const empty: Overview = {
	filters: { window: 'last_50', color: 'all', time_class: 'all' },
	profile_hash: null,
	analytics_version: 'longitudinal-v1',
	policy_version: 'support-v1',
	status: 'NO_GAMES',
	selected_game_ids: [],
	health: null,
	metrics: null,
	phases: [],
	openings: [],
	patterns: {},
	conversion: null,
	conversion_strength: false,
	recent_trends: []
};

test.beforeEach(async ({ page }) => {
	await page.route('**/health', (route) => route.fulfill({ json: { status: 'ok' } }));
	await page.route('**/api/v1/games?limit=5', (route) =>
		route.fulfill({ json: { items: [], total: 0, limit: 5, offset: 0 } })
	);
	await page.route('**/api/v1/system', (route) =>
		route.fulfill({
			json: {
				status: 'degraded',
				components: {
					database: { status: 'available' },
					stockfish: { status: 'available' },
					ollama: { status: 'unavailable' }
				},
				statistics: { games_stored: 7, games_analyzed: 4, pending_games: 3 }
			}
		})
	);
});

test('shows empty evidence without reporting a zero mean loss', async ({ page }) => {
	await page.route('**/api/v1/analytics/overview?*', (route) => route.fulfill({ json: empty }));
	await page.goto('/');
	await expect(
		page.getByText('Import and analyze completed games to see performance here.')
	).toBeVisible();
	await expect(page.getByText(/Mean loss:/)).toHaveCount(0);
});

test('keeps library totals and partial cohort coverage distinct', async ({ page }) => {
	await page.route('**/api/v1/analytics/overview?*', (route) =>
		route.fulfill({
			json: {
				...empty,
				status: 'PARTIAL',
				selected_game_ids: [3, 2, 1],
				health: { selected_games: 3, analyzed_games: 2, analyzed_player_moves: 4 }
			}
		})
	);
	await page.goto('/');
	await expect(page.getByText('7', { exact: true })).toBeVisible();
	await expect(page.getByText('4', { exact: true })).toBeVisible();
	await expect(page.getByText(/2 analyzed of 3 selected games/)).toBeVisible();
	await expect(page.getByText(/Some games in this window lack completed analysis/)).toBeVisible();
});

test('preserves working sections when analytics is unavailable', async ({ page }) => {
	await page.route('**/api/v1/analytics/overview?*', (route) =>
		route.fulfill({
			status: 503,
			json: { code: 'DATABASE_UNAVAILABLE', message: 'Database unavailable.' }
		})
	);
	await page.goto('/');
	await expect(page.getByText('Unable to load performance.')).toBeVisible();
	await expect(page.getByText('7', { exact: true })).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Recent completed games' })).toBeVisible();
});

test('treats a malformed successful response as a recoverable section error', async ({ page }) => {
	await page.route('**/api/v1/analytics/overview?*', (route) =>
		route.fulfill({ json: { ...empty, phases: null } })
	);
	await page.goto('/');
	await expect(page.getByText('Unable to load performance.')).toBeVisible();
	await expect(page.getByText('7', { exact: true })).toBeVisible();
});

test('shows backend phase and mean loss values and opens the exact recent game', async ({
	page
}) => {
	const { game, patterns } = await import('./phase17-fixtures.js');
	const report = patterns('last_50');
	const summary: NonNullable<Overview['metrics']> = {
		games_played: 12,
		wins: 6,
		draws: 3,
		losses: 3,
		score_percentage: 62.5,
		win_rate: { numerator: 6, denominator: 12, per_100: 50 },
		moves: {
			player_moves: 120,
			games_represented: 12,
			comparable_moves: 120,
			excluded_losses: 0,
			classifiable_moves: 120,
			total_loss_cp: 5400,
			mean_loss_cp: 45,
			median_loss_cp: 33,
			significant: { numerator: 3, denominator: 120, per_100: 2.5 },
			critical: { numerator: 12, denominator: 120, per_100: 10 }
		}
	};
	const overview: Overview = {
		...report,
		metrics: summary,
		phases: [
			{
				key: 'endgame',
				summary,
				evidence_status: 'sufficient',
				color_games: { black: 12 },
				time_class_games: { rapid: 12 },
				opening_names: []
			}
		],
		openings: []
	};
	await page.route('**/api/v1/analytics/overview?*', (route) => route.fulfill({ json: overview }));
	await page.route('**/api/v1/games?limit=5', (route) =>
		route.fulfill({
			json: { items: [game], total: 12, limit: 5, offset: 0 }
		})
	);
	await page.goto('/');
	await expect(page.getByText('Mean loss: 45 cp per comparable move (120 moves)')).toBeVisible();
	await expect(
		page.getByText('2.5 significant errors per 100 classifiable player moves (120 moves)')
	).toBeVisible();
	await expect(page.getByRole('link', { name: 'vs White fixture' })).toHaveAttribute(
		'href',
		'/games/17'
	);
});
