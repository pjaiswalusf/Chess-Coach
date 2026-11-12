import { expect, test } from '@playwright/test';
import { game, gameAnalysis, noMoveCoaching, scriptText } from './phase17-fixtures.js';

test.beforeEach(async ({ page }) => {
	await page.route('**/health', (route) => route.fulfill({ json: { status: 'ok' } }));
	await page.route('**/api/v1/games/17', (route) => route.fulfill({ json: game }));
	await page.route('**/api/v1/games/17/analysis*', (route) =>
		route.fulfill({ json: gameAnalysis })
	);
	await page.route('**/api/v1/games/17/coaching?*', (route) =>
		route.fulfill({ json: { status: 'insufficient_evidence', game_review: [] } })
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
	const evalBar = page.getByRole('img', { name: /Position evaluation:/ });
	await expect(evalBar).toHaveAccessibleName('Position evaluation: +0.10 (White perspective)');
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
	await expect(board.locator('[data-square="g6"]').getByTitle('Blunder')).toBeVisible();
	await expect(board.locator('[data-square="h7"]').getByTitle('Blunder')).toHaveCount(0);
	await expect(evalBar).toHaveAccessibleName('Position evaluation: +2.10 (White perspective)');
	await expect(evalBar.locator('rect')).toHaveAttribute('y', '0');
	await expect(page.getByRole('button', { name: 'Next move' })).toBeDisabled();
	await expect(page.getByText('190 cp', { exact: true })).toBeHidden();
	await page.getByRole('button', { name: '38... Kg6 — Critical error' }).click();
	await expect(board.getByTitle('h7: Black king', { exact: true })).toBeVisible();
	await expect(board.getByText('g7: empty · Engine suggestion', { exact: true })).toHaveCount(1);
	await expect(board.getByTitle('Blunder')).toHaveCount(0);
	await expect(evalBar).toHaveAccessibleName('Position evaluation: +0.20 (White perspective)');
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
	await expect(evalBar.locator('rect')).not.toHaveAttribute('y', '0');
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
	const remarks = page.getByRole('region', { name: 'Move coaching' });
	await expect(remarks.getByRole('heading', { name: 'Blunder', exact: true })).toBeVisible();
	await expect(
		remarks.getByText(
			'The king repositions to g6. But there’s a stronger continuation to consider.'
		)
	).toBeVisible();
	await expect(
		remarks.getByText('39. Qg2+ gives check, so the opponent has to answer it.')
	).toBeVisible();
	await expect(remarks.getByText('190 cp', { exact: true })).toBeHidden();
	await expect(remarks.getByText('38...Kg6 39. Qg2+', { exact: true })).toBeHidden();
	await page.getByText('Engine best line', { exact: true }).click();
	await page.getByRole('button', { name: 'Get a practice tip' }).click();
	await expect(page.getByRole('alert')).toContainText('Start Ollama');
	await expect(
		page.getByText('39. Qg2+ gives check, so the opponent has to answer it.')
	).toBeVisible();
	await expect(page.getByText('38... Kg7 moves the king from h7 to g7.')).toBeVisible();
	await expect(page.getByText('38... Kg7', { exact: true })).toBeVisible();
	await expect(page.getByRole('img', { name: /Stockfish evaluations/ })).toBeVisible();
	await page.reload();
	await expect(page.getByText('Before 38... Kg6 · Ply 2')).toBeVisible();
});

test('labels later engine moves when the backend has no selected-move remark', async ({ page }) => {
	const { assessment, played } = noMoveCoaching.move_breakdown;
	await page.route('**/api/v1/games/17/moves/2/explanation?*', (route) =>
		route.fulfill({
			json: { ...noMoveCoaching, move_breakdown: { assessment, played, alternative: null } }
		})
	);

	await page.goto('/games/17?ply=2');
	const remarks = page.getByRole('region', { name: 'Move coaching' });
	await expect(
		remarks.getByText('No remark about this move is available from the backend.')
	).toBeVisible();
	await expect(
		remarks.getByText(`Possible continuation after this move ${played.key_fact}`, {
			exact: true
		})
	).toBeVisible();
});

test('keeps the selected-move card without the Game coaching block', async ({ page }) => {
	await page.goto('/games/17?ply=2');
	const sidebar = page.getByRole('complementary', { name: 'Game analysis' });
	await expect(sidebar.getByRole('heading', { name: 'Blunder', exact: true })).toBeVisible();
	await expect(sidebar.getByRole('region', { name: 'Game coaching' })).toHaveCount(0);
});

test('keeps the engine line and interactive graph beside the board on desktop', async ({
	page
}) => {
	await page.setViewportSize({ width: 1280, height: 720 });
	await page.goto('/games/17');
	const board = page.getByRole('group', { name: /Chessboard/ });
	const sidebar = page.getByRole('complementary', { name: 'Game analysis' });
	const engineLine = sidebar.getByRole('region', { name: 'Engine best line' });
	const graph = sidebar.getByRole('slider', { name: 'Jump to position on evaluation graph' });
	await expect(engineLine).toBeHidden();
	await sidebar.getByText('Engine best line', { exact: true }).click();
	await expect(engineLine.getByText('38. a8=Q', { exact: true })).toBeVisible();
	const boardBox = (await board.boundingBox())!;
	const panelBox = (await sidebar.boundingBox())!;
	expect(panelBox.x).toBeGreaterThan(boardBox.x + boardBox.width);
	expect(panelBox.y).toBeLessThan(boardBox.y + boardBox.height);
	const viewer = page.getByRole('region', { name: 'Position viewer' });
	const viewerBox = (await viewer.boundingBox())!;
	const evalBar = (await page.getByRole('img', { name: /Position evaluation:/ }).boundingBox())!;
	expect(panelBox.width).toBeCloseTo(viewerBox.width);
	expect(evalBar.x + evalBar.width).toBeLessThan(boardBox.x);
	expect(evalBar.height).toBeCloseTo(boardBox.height);
	expect(panelBox.width).toBeGreaterThanOrEqual(475);
	const navigation = viewer.getByRole('group', { name: 'Position navigation' });
	const navigationBox = (await navigation.boundingBox())!;
	expect(navigationBox.y).toBeGreaterThan(boardBox.y + boardBox.height);
	await expect(sidebar.getByRole('group', { name: 'Position navigation' })).toHaveCount(0);

	const graphBox = (await graph.boundingBox())!;
	await graph.click({ position: { x: graphBox.width - 4, y: 30 } });
	await expect(graph).toHaveAttribute(
		'aria-valuetext',
		'After ply 2, Kg6 · Blunder · +2.10 (White perspective)'
	);
	const blunder = sidebar.getByRole('button', { name: 'Kg6 Blunder' });
	const best = sidebar.getByRole('button', { name: 'a8=Q Best' });
	await expect(blunder).toHaveAttribute('aria-pressed', 'true');
	await expect(sidebar.getByRole('heading', { name: 'Blunder', exact: true })).toBeVisible();
	const plot = sidebar.getByRole('img', { name: /Stockfish evaluations/ });
	const blunderColor = await blunder.evaluate((move) => getComputedStyle(move).color);
	const bestColor = await best.evaluate((move) => getComputedStyle(move).color);
	expect(blunderColor).not.toBe(bestColor);
	await expect(plot.locator('[data-ply="2"]')).toHaveCSS('fill', blunderColor);
	await expect(plot.locator('[data-ply="1"]')).toHaveCount(0);
	await expect(board.getByTitle('g6: Black king', { exact: true })).toBeVisible();
	await expect(engineLine.getByText('38... Kg7', { exact: true })).toBeVisible();

	await engineLine.getByRole('button', { name: 'Show best move' }).click();
	await expect(board.getByText('g7: empty · Engine suggestion', { exact: true })).toHaveCount(1);
	await expect(graph).toHaveAttribute(
		'aria-valuetext',
		'After ply 1, a8=Q · Best · +0.20 (White perspective)'
	);
	await expect(plot.locator('[data-ply="1"]')).toBeVisible();
	await expect(plot.locator('[data-ply="1"]')).not.toHaveCSS('fill', bestColor);
	await graph.press('Home');
	await expect(board.getByTitle('a7: White pawn', { exact: true })).toBeVisible();
	await expect(graph).toHaveAttribute(
		'aria-valuetext',
		'Starting position · +0.10 (White perspective)'
	);
});

test('keeps the engine line the same height as continuations get longer', async ({ page }) => {
	const longLine =
		'38...Kg7 39. Qc8 Kh7 40. Kh2 Kh6 41. Qe6+ Kg7 42. Qh6+ Kf7 43. Kg3 Ke8 44. Qf6 Kd7 45. Qd4+ Kc7 46. Qb4 Kc8 47. Qa5 Kb7 48. Qa7+ Kxa7';
	await page.route('**/api/v1/games/17/analysis*', (route) =>
		route.fulfill({
			json: {
				...gameAnalysis,
				moves: [gameAnalysis.moves[0], { ...gameAnalysis.moves[1], pv_san: longLine }]
			}
		})
	);
	await page.goto('/games/17');
	await page.getByText('Engine best line', { exact: true }).click();
	const engineLine = page.getByRole('region', { name: 'Engine best line' });
	const shortHeight = (await engineLine.boundingBox())!.height;
	await page.getByRole('button', { name: 'Final position' }).click();
	const continuation = engineLine.getByRole('region', { name: 'Engine continuation' });
	await expect(continuation).toContainText(longLine);
	expect((await engineLine.boundingBox())!.height).toBe(shortHeight);
	expect(await continuation.evaluate((element) => element.scrollHeight)).toBeGreaterThan(
		await continuation.evaluate((element) => element.clientHeight)
	);
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

test('shows coach remarks immediately at the starting position and after navigation', async ({
	page
}) => {
	await page.goto('/games/17');
	const remarks = page.getByRole('region', { name: 'Move coaching' });
	await expect(remarks.getByRole('heading', { name: 'Best', exact: true })).toBeVisible();
	await expect(
		remarks.getByText(
			'The king repositions to g6. But there’s a stronger continuation to consider.'
		)
	).toBeVisible();
	await expect(remarks.getByText('Move evidence', { exact: true })).toHaveCount(0);
	await expect(remarks.getByText('38...Kg6 39. Qg2+', { exact: true })).toBeHidden();
	await page.getByRole('button', { name: 'Next move', exact: true }).click();
	await expect(remarks.getByRole('heading', { name: 'Best', exact: true })).toBeVisible();
	await page.getByRole('button', { name: 'Next move', exact: true }).click();
	const blunder = remarks.getByRole('heading', { name: 'Blunder', exact: true });
	await expect(blunder).toBeVisible();
	await expect(blunder).toHaveClass(/#fa412d/);
	await expect(blunder.getByText('??', { exact: true })).toBeVisible();
	await page.getByRole('button', { name: 'First position', exact: true }).click();
	await expect(remarks.getByRole('heading', { name: 'Best', exact: true })).toBeVisible();
});
