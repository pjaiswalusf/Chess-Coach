import { expect, test } from '@playwright/test';
import type { GamePage } from '../src/lib/api/games.js';

const empty = { items: [], total: 0, limit: 25, offset: 0 } satisfies GamePage;
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
			eco_code: 'C20',
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
	await page.route('**/api/v1/games?limit=25&offset=0', async (route) => {
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
	await expect(page.getByRole('cell', { name: 'C20' })).toBeVisible();
	expect(requests).toBe(1);
});

test('shows an actionable empty state for a valid empty list', async ({ page }) => {
	await page.route('**/api/v1/games?limit=25&offset=0', (route) => route.fulfill({ json: empty }));
	await page.goto('/games');
	await expect(page.getByRole('heading', { name: 'No games imported yet.' })).toBeVisible();
	await page.getByRole('link', { name: 'Go to Sync' }).click();
	await expect(page).toHaveURL('/sync');
});

test('keeps API failures local and retries without a reload', async ({ page }) => {
	let requests = 0;
	await page.route('**/api/v1/games?limit=25&offset=0', (route) => {
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
	await page.route('**/api/v1/training/next', (route) =>
		route.fulfill({ json: { puzzle: null, reason: 'NO_PUZZLES_DUE' } })
	);
	await page.route('**/api/v1/training/progress', (route) =>
		route.fulfill({ json: { first_attempt_at: null, cohorts: [] } })
	);
	await page.route('**/api/v1/training/stats', (route) =>
		route.fulfill({
			json: {
				puzzles_total: 0,
				puzzles_attempted: 0,
				attempts_total: 0,
				correct_attempts: 0,
				incorrect_attempts: 0,
				accuracy: null,
				puzzles_due: 0,
				average_attempts: null,
				themes: []
			}
		})
	);
	const gate = Promise.withResolvers<void>();
	const started = page.waitForRequest('**/api/v1/games?limit=25&offset=0');
	await page.route('**/api/v1/games?limit=25&offset=0', async (route) => {
		await gate.promise;
		await route.abort();
	});
	try {
		await page.goto('/games');
		await started;
		const cancelled = page.waitForEvent('requestfailed', (request) =>
			request.url().endsWith('/api/v1/games?limit=25&offset=0')
		);
		await page.getByRole('navigation').getByRole('link', { name: 'Puzzles' }).click();
		await expect(page.getByRole('heading', { name: 'Puzzles' })).toBeVisible();
		expect((await cancelled).failure()?.errorText).toBe('net::ERR_ABORTED');
		await expect(page.getByRole('alert')).toHaveCount(0);
	} finally {
		gate.resolve();
	}
});

test('paginates 26 backend games and resets the offset for result filters', async ({ page }) => {
	const row = games.items[0];
	const dataset: GamePage['items'] = Array.from({ length: 26 }, (_, i) => ({
		...row,
		id: i + 1,
		opponent: 'Opponent ' + (i + 1),
		player_color: i % 2 ? 'black' : 'white',
		result: i === 25 ? 'loss' : i % 2 ? 'win' : 'draw',
		player_rating: i % 2 ? 1420 : 1590
	}));
	await page.route('**/api/v1/games?*', (route) => {
		const params = new URL(route.request().url()).searchParams;
		const offset = Number(params.get('offset') ?? 0);
		const result = params.get('result');
		const matching = dataset.filter((g) => !result || g.result === result);
		return route.fulfill({
			json: {
				items: matching.slice(offset, offset + 25),
				total: matching.length,
				limit: 25,
				offset
			}
		});
	});
	await page.goto('/games');
	await expect(page.getByText('Showing 1–25 of 26 games')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Previous', exact: true })).toBeDisabled();
	await page.getByRole('button', { name: 'Next', exact: true }).click();
	await expect(page).toHaveURL('/games?offset=25');
	await expect(page.getByText('Showing 26–26 of 26 games')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Next', exact: true })).toBeDisabled();
	await page.reload();
	await expect(page.getByRole('link', { name: 'vs Opponent 26' })).toHaveAttribute(
		'href',
		'/games/26'
	);
	await expect(page.getByRole('row', { name: /Opponent 26/ })).toContainText(/Black.*Loss.*1420/i);
	await page.getByRole('combobox', { name: 'Result', exact: true }).selectOption('loss');
	await expect(page).toHaveURL('/games?result=loss');
	await expect(page.getByText('Showing 1–1 of 1 games')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Next', exact: true })).toBeDisabled();
	await page.getByRole('combobox', { name: 'Result', exact: true }).selectOption('');
	await expect(page.getByText('Showing 1–25 of 26 games')).toBeVisible();
});

test('disables Next for exactly 25 results', async ({ page }) => {
	await page.route('**/api/v1/games?limit=25&offset=0', (route) =>
		route.fulfill({
			json: {
				...games,
				total: 25,
				items: Array.from({ length: 25 }, (_, i) => ({ ...games.items[0], id: i + 1 }))
			}
		})
	);
	await page.goto('/games');
	await expect(page.getByText('Showing 1–25 of 25 games')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Next', exact: true })).toBeDisabled();
});
