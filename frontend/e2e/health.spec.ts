import { expect, test } from '@playwright/test';

test('preserves the shell during a disconnection and reconnects on retry', async ({ page }) => {
	let checks = 0;
	await page.route('**/health', (route) => {
		checks += 1;
		return checks === 1 ? route.abort() : route.fulfill({ json: { status: 'ok' } });
	});
	await page.goto('/');
	await expect(page.getByText('Backend unavailable', { exact: true })).toBeVisible();
	await page.getByRole('navigation').getByRole('link', { name: 'Training' }).click();
	await expect(page.getByRole('heading', { name: 'Training' })).toBeVisible();
	await expect(page.getByText('Backend unavailable', { exact: true })).toBeVisible();
	expect(checks).toBe(1);
	await page.getByRole('button', { name: 'Retry backend connection' }).click();
	await expect(page.getByText('Backend connected', { exact: true })).toBeVisible();
	await expect(page).toHaveURL('/training');
	expect(checks).toBe(2);
});

test('treats an invalid liveness payload as unavailable', async ({ page }) => {
	await page.route('**/health', (route) => route.fulfill({ json: { status: 'healthy' } }));
	await page.goto('/');
	await expect(page.getByText('Backend unavailable', { exact: true })).toBeVisible();
});

test('shows dependency degradation while FastAPI remains connected', async ({ page }) => {
	await page.route('**/health', (route) => route.fulfill({ json: { status: 'ok' } }));
	await page.route('**/api/v1/system', (route) =>
		route.fulfill({
			json: {
				status: 'degraded',
				components: {
					database: { status: 'available' },
					stockfish: { status: 'unknown' },
					ollama: { status: 'unavailable' }
				},
				statistics: { games_stored: 24, games_analyzed: 12, pending_games: 12 }
			}
		})
	);
	await page.goto('/system');
	await expect(page.getByText('Backend connected', { exact: true })).toBeVisible();
	await expect(page.getByText('Degraded', { exact: true })).toBeVisible();
	const ollama = page.getByText('Ollama', { exact: true }).locator('..');
	await expect(ollama.getByText('Unavailable', { exact: true })).toBeVisible();
	await expect(ollama.getByText(/Start Ollama/)).toBeVisible();
	await expect(page.getByText('24', { exact: true })).toBeVisible();
});

test('reports unavailable database counts without treating them as zero', async ({ page }) => {
	await page.route('**/health', (route) => route.fulfill({ json: { status: 'ok' } }));
	await page.route('**/api/v1/system', (route) =>
		route.fulfill({
			json: {
				status: 'unavailable',
				components: {
					database: { status: 'unavailable' },
					stockfish: { status: 'unknown' },
					ollama: { status: 'available' }
				},
				statistics: null
			}
		})
	);
	await page.goto('/system');
	await expect(page.getByText('Backend connected', { exact: true })).toBeVisible();
	await expect(page.getByText(/Check database access/)).toBeVisible();
	await expect(page.getByText('Game counts are unavailable.')).toBeVisible();
	await expect(page.getByText('Games stored', { exact: true })).toHaveCount(0);
});

test('distinguishes a missing local model and clears connectivity on refresh', async ({ page }) => {
	let offline = false;
	await page.route('**/health', (route) =>
		offline ? route.abort() : route.fulfill({ json: { status: 'ok' } })
	);
	await page.route('**/api/v1/system', (route) =>
		offline
			? route.abort()
			: route.fulfill({
					json: {
						status: 'degraded',
						checked_at: '2026-01-01T00:00:00Z',
						analysis_version: 'single-v1',
						components: {
							database: { status: 'available' },
							stockfish: { status: 'available', version: 'Stockfish fixture' },
							ollama: { status: 'available', model: 'local-fixture', model_status: 'unavailable' }
						},
						statistics: {
							games_stored: 24,
							games_analyzed: 12,
							pending_games: 12,
							positions_cached: 240,
							active_sync_runs: 0,
							active_analysis_runs: 1,
							active_coaching_jobs: 0
						}
					}
				})
	);
	await page.goto('/system');
	await expect(page.getByText('Backend connected', { exact: true })).toHaveCount(1);
	await expect(
		page.getByText('Ollama', { exact: true }).locator('..').getByText('Available', { exact: true })
	).toBeVisible();
	await expect(
		page
			.getByText('Ollama model', { exact: true })
			.locator('..')
			.getByText('Unavailable', { exact: true })
	).toBeVisible();
	await expect(page.getByText('240', { exact: true })).toBeVisible();
	offline = true;
	await page.getByRole('button', { name: 'Refresh status' }).click();
	await expect(page.getByText('Backend unavailable', { exact: true })).toBeVisible();
	await expect(page.getByText('Backend connected', { exact: true })).toHaveCount(0);
	await expect(page.getByText('240', { exact: true })).toHaveCount(0);
});
