import { expect, test } from '@playwright/test';
import { game, gameAnalysis, noMoveCoaching, scriptText } from './phase17-fixtures.js';

test.beforeEach(async ({ page }) => {
	await page.route('**/health', (route) => route.fulfill({ json: { status: 'ok' } }));
	await page.route('**/api/v1/games/17', (route) => route.fulfill({ json: game }));
	await page.route('**/api/v1/games/17/analysis*', (route) =>
		route.fulfill({ json: gameAnalysis })
	);
	await page.route('**/api/v1/games/17/moves/*/explanation?*', (route) =>
		route.request().method() === 'POST'
			? route.fulfill({
					status: 503,
					json: { code: 'OLLAMA_UNAVAILABLE', message: 'Start Ollama and retry.' }
				})
			: route.fulfill({ json: noMoveCoaching })
	);
});

test('reviews a custom start, a promotion, and the final Black move on a narrow screen', async ({
	page
}) => {
	await page.setViewportSize({ width: 375, height: 750 });
	await page.goto('/games/17');
	const board = page.getByRole('group', { name: 'Chessboard · Black at bottom' });
	await expect(board.locator('[data-square]').first()).toHaveAttribute('data-square', 'h1');
	await expect(board.getByTitle('a7: White pawn', { exact: true })).toBeVisible();
	await expect(board.locator('[data-square="a7"] img')).toHaveJSProperty('naturalWidth', 800);
	await page.getByRole('button', { name: 'Next move' }).focus();
	await page.keyboard.press('Enter');
	await expect(board.getByTitle('a8: White queen', { exact: true })).toBeVisible();
	const promoted = board.locator('[data-square="a8"] img');
	await expect(promoted).toHaveAttribute('src', /\/wQ\.svg$/);
	await expect(promoted).toHaveJSProperty('naturalWidth', 800);
	await page.getByRole('button', { name: 'Final position' }).click();
	await expect(board.getByTitle('g6: Black king', { exact: true })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Next move' })).toBeDisabled();
	await expect(page.getByText('190 cp', { exact: true })).toBeVisible();
	await expect(page.getByText('+210 cp', { exact: true })).toBeVisible();
	await page.getByRole('button', { name: '38... Kg6 — Critical error' }).click();
	await expect(board.getByTitle('h7: Black king', { exact: true })).toBeVisible();
	await expect(board.getByText('g7: empty · Engine suggestion', { exact: true })).toHaveCount(1);
	await page.getByRole('button', { name: 'Next move' }).click();
	await expect(board.getByTitle('g6: Black king', { exact: true })).toBeVisible();
	await page.getByRole('button', { name: 'Previous move' }).click();
	await expect(board.getByTitle('h7: Black king', { exact: true })).toBeVisible();
	await page.getByRole('button', { name: 'Flip board' }).click();
	await expect(
		page
			.getByRole('group', { name: 'Chessboard · White at bottom' })
			.locator('[data-square]')
			.first()
	).toHaveAttribute('data-square', 'a8');
	await page.getByText('Completed game PGN', { exact: true }).click();
	await expect(page.getByText(scriptText, { exact: false })).toBeVisible();
	expect(await page.evaluate(() => Reflect.has(globalThis, 'phase17Injected'))).toBe(false);
	await expect
		.poll(() => page.evaluate(() => document.documentElement.scrollWidth))
		.toBeLessThanOrEqual(375);
});

test('keeps engine evidence and evaluation available when Ollama is down', async ({ page }) => {
	await page.goto('/games/17?ply=2');
	await expect(page.getByText('Before 38... Kg6 · Ply 2')).toBeVisible();
	await page.getByRole('button', { name: 'Explain this move' }).click();
	await expect(page.getByRole('alert')).toContainText('Start Ollama');
	await expect(page.getByText('h7g7', { exact: true })).toHaveCount(2);
	await expect(page.getByRole('img', { name: /Stockfish evaluations/ })).toBeVisible();
	await page.reload();
	await expect(page.getByText('Before 38... Kg6 · Ply 2')).toBeVisible();
});

test('keeps pending game metadata visible and refuses invalid FEN', async ({ page }) => {
	await page.route('**/api/v1/games/17/analysis*', (route) =>
		route.fulfill({
			json: { ...gameAnalysis, status: 'pending', initial_fen: null, moves: [] }
		})
	);
	await page.goto('/games/17');
	await expect(page.getByRole('heading', { name: 'White fixture vs Black fixture' })).toBeVisible();
	await expect(page.getByText('Analysis is pending for this game.')).toBeVisible();
	await expect(page.locator('[data-square]')).toHaveCount(0);
	await page.route('**/api/v1/games/17/analysis*', (route) =>
		route.fulfill({
			json: {
				...gameAnalysis,
				moves: [gameAnalysis.moves[0], { ...gameAnalysis.moves[1], fen_after: 'invalid' }]
			}
		})
	);
	await page.getByRole('button', { name: 'Refresh analysis' }).click();
	await page.getByRole('button', { name: 'Final position' }).click();
	await expect(page.getByRole('alert')).toContainText('Position cannot be displayed');
	await expect(page.locator('[data-square]')).toHaveCount(0);
});

test('shows a safe missing-game state and a route 404 for invalid IDs', async ({ page }) => {
	await page.route('**/api/v1/games/999**', (route) =>
		route.fulfill({
			status: 404,
			json: { code: 'GAME_NOT_FOUND', message: 'The requested game was not found.' }
		})
	);
	await page.goto('/games/999');
	await expect(page.getByRole('alert')).toContainText('The requested game was not found.');
	await expect(page.getByRole('link', { name: 'Back to Games' })).toBeVisible();
	const response = await page.goto('/games/not-a-number');
	expect(response?.status()).toBe(404);
	await expect(page.getByRole('heading', { name: 'Page not found' })).toBeVisible();
});
