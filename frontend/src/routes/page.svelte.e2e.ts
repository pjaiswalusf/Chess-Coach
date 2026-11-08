import { expect, test } from '@playwright/test';

const worker = {
	available: true,
	engine_version: 'Stockfish fixture',
	heartbeat_at: '2026-11-08T00:00:00Z',
	database: 'healthy',
	players: [{ id: 1, username: 'testplayer' }]
};
const run = {
	id: 1,
	tracked_player_id: 1,
	status: 'queued',
	games_total: 2,
	games_completed: 0,
	games_failed: 0,
	games_skipped: 0,
	games_excluded: 1,
	positions_analyzed: 0,
	cache_hits: 0,
	progress_percent: 0,
	engine_version: 'Stockfish fixture',
	engine_config_json: { nodes: 10000 },
	worker_available: true,
	cancel_requested: false,
	profile_hash: 'a'.repeat(64),
	games: [],
	error_code: null,
	error_message: null,
	last_heartbeat_at: null
};

test('start, persist across reload, cancel and retry', async ({ page }) => {
	let current: typeof run | null = null;
	let starts = 0;
	await page.route('**/api/v1/analysis-worker', (route) => route.fulfill({ json: worker }));
	await page.route('**/api/v1/analysis-runs', async (route) => {
		if (route.request().method() === 'POST') {
			starts += 1;
			current = { ...run, id: starts };
			await route.fulfill({ status: 202, json: current });
		} else await route.fulfill({ json: current ? [current] : [] });
	});
	await page.route('**/api/v1/analysis-runs/*/cancel', async (route) => {
		current = { ...run, status: 'failed', cancel_requested: true };
		await route.fulfill({ json: current });
	});
	await page.goto('/');
	await expect(page.getByText('No analysis runs yet.')).toBeVisible();
	await page.getByRole('button', { name: 'Analyze eligible games' }).click();
	await expect(page.getByRole('heading', { name: 'Run #1 · queued' })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Analyze eligible games' })).toBeDisabled();
	await page.reload();
	await expect(page.getByRole('heading', { name: 'Run #1 · queued' })).toBeVisible();
	await page.getByRole('button', { name: 'Cancel run' }).click();
	await expect(page.getByRole('heading', { name: 'Run #1 · failed' })).toBeVisible();
	await page.getByRole('button', { name: 'Retry eligible games' }).click();
	await expect(page.getByRole('heading', { name: 'Run #2 · queued' })).toBeVisible();
	expect(starts).toBe(2);
});

test('worker outage and request errors are actionable', async ({ page }) => {
	await page.route('**/api/v1/analysis-worker', (route) =>
		route.fulfill({ json: { ...worker, available: false } })
	);
	await page.route('**/api/v1/analysis-runs', (route) =>
		route.fulfill({ json: [{ ...run, status: 'running', worker_available: false }] })
	);
	await page.goto('/');
	await expect(page.getByText('Worker unavailable. Restart it', { exact: false })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Analyze eligible games' })).toBeDisabled();
	await page.route('**/api/v1/analysis-worker', (route) =>
		route.fulfill({ status: 503, json: { message: 'Check database access.' } })
	);
	await page.reload();
	await expect(page.getByRole('alert')).toHaveText('Check database access.');
});

test('completed evidence keeps mate separate', async ({ page }) => {
	await page.route('**/api/v1/analysis-worker', (route) => route.fulfill({ json: worker }));
	await page.route('**/api/v1/analysis-runs', (route) =>
		route.fulfill({
			json: [
				{
					...run,
					status: 'completed',
					games_completed: 2,
					progress_percent: 100,
					games: [{ game_id: 42, status: 'done', error_code: null }]
				}
			]
		})
	);
	await page.route('**/api/v1/games/42/analysis?*', (route) =>
		route.fulfill({
			json: {
				moves: [
					{
						ply: 4,
						played_move_san: 'Qh4#',
						best_move_uci: 'd8h4',
						mate_after_white: 0,
						mate_after_winner: false,
						loss_cp: null
					}
				]
			}
		})
	);
	await page.goto('/');
	await page.getByText('Games and evidence').click();
	await page.getByRole('button', { name: 'View moves for game 42' }).click();
	await expect(page.getByRole('cell', { name: 'Mate 0 (Black)' })).toBeVisible();
	await expect(page.getByRole('cell', { name: 'Qh4#' })).toBeVisible();
});
