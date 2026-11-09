import { expect, test } from '@playwright/test';
import {
	game,
	gameAnalysis,
	noHistoricalCoaching,
	noMoveCoaching,
	patterns
} from './phase17-fixtures.js';

test('imports and analyzes completed games, then follows measured coaching evidence to a move', async ({
	page
}) => {
	let username: string | null = null;
	let syncStarts = 0;
	let syncReads = 0;
	let analysisStarts = 0;
	let analysisReads = 0;
	const postPaths: string[] = [];
	page.on('request', (request) => {
		if (request.method() === 'POST') postPaths.push(new URL(request.url()).pathname);
	});
	await page.route('**/health', (route) => route.fulfill({ json: { status: 'ok' } }));
	await page.route('**/api/v1/system', (route) =>
		route.fulfill({
			json: {
				status: 'degraded',
				components: {
					database: { status: 'available' },
					stockfish: { status: 'available', version: 'Fixture engine' },
					ollama: { status: 'unavailable', model: 'fixture', model_status: 'unknown' }
				},
				statistics: { games_stored: 12, games_analyzed: 12, pending_games: 0 }
			}
		})
	);
	await page.route('**/api/v1/player', (route) => {
		if (route.request().method() === 'PUT') {
			const input = route.request().postDataJSON();
			expect(input.verify).toBe(true);
			username = input.username.toLowerCase();
		}
		return route.fulfill({
			json: {
				configured: username !== null,
				player: username && {
					id: 1,
					platform: 'chess.com',
					username
				}
			}
		});
	});
	await page.route('**/api/v1/sync-runs/latest-work', (route) =>
		route.fulfill({
			json: { sync_run_id: syncStarts ? 3 : null, analysis_run_id: analysisStarts ? 4 : null }
		})
	);
	await page.route('**/api/v1/sync-runs', (route) => {
		expect(route.request().method()).toBe('POST');
		syncStarts++;
		return route.fulfill({ status: 202, json: { run_id: 3, status: 'queued' } });
	});
	await page.route('**/api/v1/sync-runs/3', (route) => {
		const running = ++syncReads === 1;
		return route.fulfill({
			json: {
				run_id: 3,
				status: running ? 'running' : 'completed',
				partial: false,
				progress: {
					archives_total: 1,
					archives_processed: running ? 0 : 1,
					games_seen: running ? 0 : 12,
					games_inserted: running ? 0 : 12,
					games_existing: 0,
					games_skipped: 0,
					games_failed: 0
				},
				error: null,
				recoverable: running
			}
		});
	});
	await page.route('**/api/v1/analysis-runs', (route) => {
		expect(route.request().postDataJSON()).toEqual({ scope: 'pending' });
		analysisStarts++;
		return route.fulfill({ status: 202, json: { run_id: 4, status: 'queued' } });
	});
	await page.route('**/api/v1/analysis-runs/4/progress', (route) => {
		const running = ++analysisReads === 1;
		return route.fulfill({
			json: {
				run_id: 4,
				status: running ? 'running' : 'completed',
				storage_status: running ? 'running' : 'done',
				worker_available: true,
				games_total: 12,
				games_completed: running ? 6 : 12,
				games_failed: 0,
				games_skipped: 0,
				games_excluded: 0,
				games_remaining: running ? 6 : 0
			}
		});
	});
	await page.route('**/api/v1/games?*', (route) => {
		const limit = Number(new URL(route.request().url()).searchParams.get('limit'));
		return route.fulfill({
			json: {
				items: analysisReads > 1 ? [game] : [],
				total: analysisReads > 1 ? 1 : 0,
				limit,
				offset: 0
			}
		});
	});
	await page.route('**/api/v1/games/17', (route) => route.fulfill({ json: game }));
	await page.route('**/api/v1/games/17/analysis*', (route) =>
		route.fulfill({ json: gameAnalysis })
	);
	await page.route('**/api/v1/games/17/moves/*/explanation?*', (route) =>
		route.fulfill({ json: noMoveCoaching })
	);
	await page.route('**/api/v1/analytics/overview?*', (route) => {
		const report = patterns('last_50');
		return route.fulfill({ json: { ...report, phases: [], openings: [], metrics: null } });
	});
	await page.route('**/api/v1/analytics/patterns?*', (route) =>
		route.fulfill({ json: patterns('last_50') })
	);
	await page.route('**/api/v1/coaching/history?*', (route) =>
		route.fulfill({ json: noHistoricalCoaching })
	);
	await page.route('**/api/v1/system/llm', (route) =>
		route.fulfill({
			json: { status: 'server_unavailable', model: 'fixture' }
		})
	);

	await page.goto('/');
	const nav = page.getByRole('navigation', { name: 'Main navigation' });
	await nav.getByRole('link', { name: 'Sync' }).click();
	await page.getByLabel('Chess.com username').fill('Fixture_player');
	await page.getByRole('button', { name: 'Sync Games' }).click();
	await expect(page.getByText('Sync run #3')).toBeVisible();
	await expect(page.getByText(/New games: 12/)).toBeVisible();
	await page.getByRole('button', { name: 'Analyze Pending Games' }).click();
	await expect(page.getByText('Analysis run #4')).toBeVisible();
	await expect(page.getByText(/Analyzed: 12/)).toBeVisible();
	await nav.getByRole('link', { name: 'Games' }).click();
	await page.getByRole('link', { name: 'vs White fixture' }).click();
	await expect(page).toHaveURL('/games/17');
	await page.getByRole('button', { name: '38... Kg6 — Critical error' }).click();
	await expect(page.getByText('Before 38... Kg6 · Ply 2')).toBeVisible();
	await expect(page.getByText('h7g7', { exact: true })).toHaveCount(2);
	await nav.getByRole('link', { name: 'Coach' }).click();
	await expect(page.getByText('12 critical errors in 120 opportunities')).toBeVisible();
	await page.getByRole('link', { name: 'Game 17, ply 2' }).click();
	await expect(page.getByText('Before 38... Kg6 · Ply 2')).toBeVisible();
	expect(postPaths).toEqual(['/api/v1/sync-runs', '/api/v1/analysis-runs']);
});
