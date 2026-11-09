import { expect, test } from '@playwright/test';
import type { GamePage } from '../src/lib/api/games.js';

const empty = { items: [], total: 0, limit: 20, offset: 0 } satisfies GamePage;
const games = {
	...empty,
	total: 1,
	items: [
		{
			id: 4,
			opponent: 'Example opponent',
			result: 'draw',
			player_color: 'white',
			played_at: '2026-01-01T00:00:00Z',
			time_class: 'rapid',
			opening_name: null,
			analysis_status: 'pending'
		}
	]
} satisfies GamePage;

test.beforeEach(async ({ page }) => {
	await page.route('**/health', (route) => route.fulfill({ json: { status: 'ok' } }));
});

test('shows loading then real response values with one request per entry', async ({ page }) => {
	const gate = Promise.withResolvers<void>();
	let requests = 0;
	await page.route('**/api/v1/games', async (route) => {
		requests++;
		await gate.promise;
		await route.fulfill({ json: games });
	});
	try {
		await page.goto('/games');
		await expect(page.getByText('Loading games…')).toBeVisible();
	} finally {
		gate.resolve();
	}
	await expect(page.getByText('vs Example opponent', { exact: true })).toBeVisible();
	await expect(page.getByText('Draw', { exact: true })).toBeVisible();
	expect(requests).toBe(1);
});

test('shows an actionable empty state for a valid empty list', async ({ page }) => {
	await page.route('**/api/v1/games', (route) => route.fulfill({ json: empty }));
	await page.goto('/games');
	await expect(page.getByRole('heading', { name: 'No games imported yet.' })).toBeVisible();
	await page.getByRole('link', { name: 'Go to Sync' }).click();
	await expect(page).toHaveURL('/sync');
});

test('keeps API failures local and retries without a reload', async ({ page }) => {
	let requests = 0;
	await page.route('**/api/v1/games', (route) => {
		requests++;
		return requests === 1
			? route.fulfill({ status: 500, json: { message: 'Raw internal details' } })
			: route.fulfill({ json: games });
	});
	await page.goto('/games');
	await expect(page.getByRole('alert')).toContainText('Unable to load games.');
	await expect(page.getByRole('alert')).toContainText('Request failed (500)');
	await expect(page.getByText('Raw internal details')).toHaveCount(0);
	await expect(page.getByText('No games imported yet.')).toHaveCount(0);
	await expect(page.getByRole('navigation')).toBeVisible();
	await page.getByRole('button', { name: 'Retry', exact: true }).click();
	await expect(page.getByText('vs Example opponent', { exact: true })).toBeVisible();
	expect(requests).toBe(2);
});

test('cancels an outstanding game request when navigating away', async ({ page }) => {
	const gate = Promise.withResolvers<void>();
	const started = page.waitForRequest('**/api/v1/games');
	await page.route('**/api/v1/games', async (route) => {
		await gate.promise;
		await route.abort();
	});
	try {
		await page.goto('/games');
		await started;
		const cancelled = page.waitForEvent('requestfailed', (request) =>
			request.url().endsWith('/api/v1/games')
		);
		await page.getByRole('navigation').getByRole('link', { name: 'Coach' }).click();
		await expect(page.getByRole('heading', { name: 'Coach' })).toBeVisible();
		expect((await cancelled).failure()?.errorText).toBe('net::ERR_ABORTED');
		await expect(page.getByRole('alert')).toHaveCount(0);
	} finally {
		gate.resolve();
	}
});
