import { expect, test } from '@playwright/test';
import type { SyncRun } from '../src/lib/api/jobs.js';

const running: SyncRun = {
	run_id: 12,
	status: 'running',
	partial: false,
	started_at: null,
	finished_at: null,
	progress: {
		archives_total: 4,
		archives_processed: 2,
		games_seen: 12,
		games_inserted: 7,
		games_existing: 4,
		games_failed: 1,
		games_skipped: 0,
		games_quarantined: 0
	},
	error: null,
	recoverable: true
};

test('keeps one sync run through duplicate clicks, reload, and temporary disconnection', async ({
	page
}) => {
	await page.clock.install();
	let player: string | null = null;
	let starts = 0;
	let reads = 0;
	let drop = false;
	let finish = false;
	const base = '**/api/v1';
	await page.route('**/health', (route) => route.fulfill({ json: { status: 'ok' } }));
	await page.route(base + '/player', (route) => {
		if (route.request().method() === 'PUT') player = route.request().postDataJSON().username;
		return route.fulfill({
			json: {
				configured: player !== null,
				player: player && { id: 1, platform: 'chess.com', username: player }
			}
		});
	});
	await page.route(base + '/sync-runs/latest-work', (route) =>
		route.fulfill({
			json: {
				sync_run_id: starts ? 12 : null,
				analysis_run_id: null
			}
		})
	);
	await page.route(base + '/sync-runs', (route) => {
		starts++;
		return route.fulfill({ status: 202, json: { run_id: 12, status: 'queued' } });
	});
	await page.route(base + '/sync-runs/12', (route) => {
		reads++;
		if (drop) return route.abort();
		return route.fulfill({
			json: finish ? { ...running, status: 'failed', partial: true } : running
		});
	});

	await page.goto('/sync');
	const start = page.getByRole('button', { name: 'Sync Games' });
	await expect(start).toBeEnabled();
	await start.click();
	await expect(page.getByRole('alert')).toContainText('Enter a Chess.com username');
	expect(starts).toBe(0);
	await page.getByLabel('Chess.com username').fill('  local_player  ');
	await start.dblclick();
	await expect(page.getByText('Sync run #12')).toBeVisible();
	await expect(page.getByText(/Games seen: 12[\s\S]*Failed imports: 1/)).toBeVisible();
	expect(starts).toBe(1);
	await expect(start).toBeDisabled();

	drop = true;
	await page.reload();
	await expect(page.getByText('Sync run #12')).toBeVisible();
	await expect(page.getByText(/Reconnecting to sync status/)).toBeVisible();
	await expect(start).toBeDisabled();
	drop = false;
	finish = true;
	await page.clock.fastForward(2500);
	await expect(page.getByText('Completed with failures', { exact: true })).toBeVisible();
	await expect(page.getByText(/New games: 7/)).toBeVisible();
	const terminalReads = reads;
	await page.clock.fastForward(10000);
	expect(reads).toBe(terminalReads);
	expect(starts).toBe(1);
});

test('recovers the existing analysis after a competing tab won admission', async ({ page }) => {
	let starts = 0;
	let latest: number | null = null;
	await page.route('**/health', (route) => route.fulfill({ json: { status: 'ok' } }));
	await page.route('**/api/v1/player', (route) =>
		route.fulfill({
			json: {
				configured: true,
				player: { id: 1, platform: 'chess.com', username: 'local_player' }
			}
		})
	);
	await page.route('**/api/v1/sync-runs/latest-work', (route) =>
		route.fulfill({
			json: {
				sync_run_id: null,
				analysis_run_id: latest
			}
		})
	);
	await page.route('**/api/v1/analysis-runs', (route) => {
		starts++;
		latest = 41;
		return route.fulfill({
			status: 409,
			json: { code: 'ANALYSIS_ALREADY_RUNNING', message: 'Wait for the active run.' }
		});
	});
	await page.route('**/api/v1/analysis-runs/41/progress', (route) =>
		route.fulfill({
			json: {
				run_id: 41,
				status: 'completed',
				storage_status: 'done',
				games_total: 4,
				games_completed: 0,
				games_failed: 0,
				games_skipped: 4,
				games_excluded: 0,
				games_remaining: 0
			}
		})
	);
	await page.goto('/sync');
	await page.getByRole('button', { name: 'Analyze Pending Games' }).click();
	await expect(page.getByText('Analysis run #41')).toBeVisible();
	await expect(page.getByText('No pending games were eligible for analysis.')).toBeVisible();
	expect(starts).toBe(1);
});

test('a failed sync admission is recoverable and does not retry the POST', async ({ page }) => {
	let starts = 0;
	await page.route('**/health', (route) => route.fulfill({ json: { status: 'ok' } }));
	await page.route('**/api/v1/player', (route) =>
		route.fulfill({
			json: {
				configured: true,
				player: { id: 1, platform: 'chess.com', username: 'fixture' }
			}
		})
	);
	await page.route('**/api/v1/sync-runs/latest-work', (route) =>
		route.fulfill({ json: { sync_run_id: null, analysis_run_id: null } })
	);
	await page.route('**/api/v1/sync-runs', (route) => {
		starts++;
		return route.fulfill({
			status: 503,
			json: { code: 'DATABASE_UNAVAILABLE', message: 'Stored games are temporarily unavailable.' }
		});
	});
	await page.goto('/sync');
	const start = page.getByRole('button', { name: 'Sync Games' });
	await start.click();
	await expect(page.getByRole('alert')).toContainText('Stored games are temporarily unavailable.');
	await expect(start).toBeEnabled();
	await page.reload();
	await expect(start).toBeEnabled();
	expect(starts).toBe(1);
});
