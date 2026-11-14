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
		route.fulfill({
			json: route.request().url().includes('/moves/2/explanation')
				? noMoveCoaching
				: {
						...noMoveCoaching,
						move_breakdown: {
							...noMoveCoaching.move_breakdown,
							remark: 'The pawn reaches the back rank and becomes a queen.'
						}
					}
		})
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
	await page.getByRole('button', { name: '38... Kg6 — Blunder' }).click();
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
	await page.route('**/api/v1/games/17/moves/2/explanation?*', (route) =>
		route.fulfill({
			json: {
				...noMoveCoaching,
				status: 'failed',
				error_code: 'OLLAMA_UNAVAILABLE',
				message: 'Start Ollama and retry.'
			}
		})
	);
	await page.goto('/games/17?ply=2');
	await expect(page.getByText('Before 38... Kg6 · Ply 2')).toBeVisible();
	const remarks = page.getByRole('region', { name: 'Move coaching' });
	await expect(remarks.getByRole('heading', { name: 'Blunder', exact: true })).toBeVisible();
	await expect(remarks.getByText('After g6, a6+ gives check. Play g7 instead.')).toBeVisible();
	await expect(remarks.getByRole('img', { name: 'king' })).toHaveCount(2);
	await expect(remarks.getByRole('img', { name: 'queen' })).toBeVisible();
	await expect(remarks.getByText('190 cp', { exact: true })).toBeHidden();
	await expect(remarks.getByText('38...Kg6 39. Qa6+', { exact: true })).toBeHidden();
	await expect(remarks.getByRole('button', { name: 'Get a practice tip' })).toHaveCount(0);
	await expect(remarks.getByText('Start Ollama', { exact: false })).toHaveCount(0);
	await expect(remarks.getByText('Possible continuation after this move')).toHaveCount(0);
	await expect(remarks.getByText('Stockfish’s alternative')).toHaveCount(0);
	await expect(remarks.getByText(noMoveCoaching.move_breakdown.played.key_fact)).toHaveCount(0);
	await expect(remarks.getByText(noMoveCoaching.move_breakdown.alternative.key_fact)).toHaveCount(
		0
	);
	await expect(page.getByTitle('38... Kg7', { exact: true })).toBeVisible();
	await expect(page.getByRole('img', { name: /Stockfish evaluations/ })).toBeVisible();
	await page.reload();
	await expect(page.getByText('Before 38... Kg6 · Ply 2')).toBeVisible();
});

test('shows an empty remark state when the backend has no selected-move remark', async ({
	page
}) => {
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
	await expect(remarks.getByText(played.key_fact)).toHaveCount(0);
});

test('keeps move commentary while hiding a saved practice tip', async ({ page }) => {
	await page.route('**/api/v1/games/17/moves/2/explanation?*', (route) =>
		route.fulfill({
			json: {
				...noMoveCoaching,
				status: 'done',
				coach: {
					summary: 'Review this move.',
					what_went_wrong: 'The king stepped into a check.',
					lesson: 'Look for checks.',
					practice_tip: 'Practice responding to checks.'
				}
			}
		})
	);
	await page.goto('/games/17?ply=2');
	const sidebar = page.getByRole('complementary', { name: 'Game analysis' });
	await expect(sidebar.getByRole('heading', { name: 'Blunder', exact: true })).toBeVisible();
	await expect(sidebar.getByText('After g6, a6+ gives check. Play g7 instead.')).toBeVisible();
	await expect(sidebar.getByText('Practice this position')).toHaveCount(0);
	await expect(sidebar.getByText('Practice responding to checks.')).toHaveCount(0);
	await expect(sidebar.getByRole('region', { name: 'Game coaching' })).toHaveCount(0);
});

test('keeps the engine line and interactive graph beside the board on desktop', async ({
	page
}) => {
	await page.setViewportSize({ width: 1280, height: 720 });
	await page.goto('/games/17');
	const board = page.getByRole('group', { name: /Chessboard/ });
	const sidebar = page.getByRole('complementary', { name: 'Game analysis' });
	const engineLine = sidebar.getByRole('region', { name: 'Engine lines' });
	const graph = sidebar.getByRole('slider', { name: 'Jump to position on evaluation graph' });
	await expect(engineLine).toBeVisible();
	await expect(engineLine.getByTitle('38. a8=Q', { exact: true })).toBeVisible();
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
	const king = blunder.getByRole('img', { name: 'king' });
	const queen = best.getByRole('img', { name: 'queen' });
	await expect(king).toHaveCSS('mask-image', /\/bK\.svg/);
	await expect(king).toHaveCSS('background-color', blunderColor);
	await expect(queen).toHaveCSS('background-color', bestColor);
	expect(blunderColor).not.toBe(bestColor);
	await expect(plot.locator('[data-ply="2"]')).toBeVisible();
	await expect(plot.locator('[data-ply="2"]')).not.toHaveCSS('fill', blunderColor);
	await expect(plot.locator('[data-swing]')).toHaveCount(0);
	await expect(plot.locator('[data-ply="1"]')).toHaveCount(0);
	await expect(board.getByTitle('g6: Black king', { exact: true })).toBeVisible();
	await expect(engineLine.getByTitle('38... Kg7', { exact: true })).toHaveCount(0);

	await page.getByRole('button', { name: 'Previous move' }).click();
	await expect(engineLine.getByTitle('38... Kg7', { exact: true })).toBeVisible();
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

test('plots the recorded game through forced mate without stretching its score scale', async ({
	page
}) => {
	await page.goto('/games/17');
	const plot = page.getByRole('img', { name: /Stockfish evaluations from/ });
	const start = plot.locator('[data-ply="0"]');
	await expect(start).toBeVisible();
	const startY = await start.getAttribute('cy');

	const [first, second] = gameAnalysis.moves;
	await page.route('**/api/v1/games/17/analysis*', (route) =>
		route.fulfill({
			json: {
				...gameAnalysis,
				moves: [
					{ ...first, eval_after_cp_white: 1400 },
					{
						...second,
						eval_before_cp_white: 1400,
						eval_after_cp_white: null,
						mate_after_white: 1,
						mate_after_winner: true
					}
				]
			}
		})
	);
	await page.reload();
	await expect(start).toHaveAttribute('cy', startY!);
	const path = plot.locator('[data-series="evaluation"]');
	await expect(path).toHaveAttribute('d', /^M0 \S+ L200 \S+ L400 0$/);
	await expect(plot.locator('[data-series="evaluation-fill"]')).toHaveAttribute(
		'd',
		/^M0 108L0 \S+ L200 \S+ L400 0L400 108Z$/
	);
	await expect(start).toHaveAttribute('cx', '5');
	await expect(plot.locator('[data-swing]')).toHaveCount(2);
	await page.getByRole('button', { name: 'Final position' }).click();
	await expect(plot.locator('[data-ply="2"]')).toHaveAttribute('cx', '395');
	await expect(
		page.getByRole('slider', { name: 'Jump to position on evaluation graph' })
	).toHaveAttribute('aria-valuetext', /White mates in 1/);
});

test('shows no white area while Black has a forced mate', async ({ page }) => {
	const [first, second] = gameAnalysis.moves;
	await page.route('**/api/v1/games/17/analysis*', (route) =>
		route.fulfill({
			json: {
				...gameAnalysis,
				moves: [
					{
						...first,
						eval_after_cp_white: null,
						mate_after_white: -2,
						mate_after_winner: false
					},
					{
						...second,
						eval_before_cp_white: null,
						mate_before_white: -2,
						mate_before_winner: false,
						eval_after_cp_white: null,
						mate_after_white: -1,
						mate_after_winner: false
					}
				]
			}
		})
	);
	await page.goto('/games/17');
	const plot = page.getByRole('img', { name: /Stockfish evaluations from/ });
	await expect(plot.locator('[data-series="evaluation-fill"]')).toHaveAttribute(
		'd',
		/L200 108 L400 108L400 108Z$/
	);
	await page.getByRole('button', { name: 'Next move', exact: true }).click();
	await expect(plot.locator('[data-ply="1"]')).toHaveAttribute('cy', '103');
	await expect(
		page.getByRole('slider', { name: 'Jump to position on evaluation graph' })
	).toHaveAttribute('aria-valuetext', /Black mates in 2/);
});

test('shows two compact ranked engine lines for the displayed position', async ({ page }) => {
	const longLine =
		'38... Kg7 39. Qc8 Kh7 40. Kh2 Kh6 41. Qe6+ Kg7 42. Qh6+ Kf7 43. Kg3 Ke8 44. Qf6 Kd7 45. Qd4+ Kc7 46. Qb4 Kc8 47. Qa5 Kb7 48. Qa7+ Kxa7';
	await page.setViewportSize({ width: 375, height: 750 });
	await page.route('**/api/v1/games/17/review/variation', (route) => {
		const { ply, line } = route.request().postDataJSON();
		expect(line).toEqual([]);
		const root = ply === 0;
		return route.fulfill({
			json: {
				fen: root ? gameAnalysis.initial_fen : gameAnalysis.moves[0].fen_after,
				side_to_move: root ? 'white' : 'black',
				san: null,
				outcome: null,
				legal_moves: gameAnalysis.legal_moves_by_ply[ply],
				evaluation: {
					cp: 82,
					mate: null,
					white_wins: null,
					best_move: root ? 'a7a8q' : 'h7g7',
					continuation: root ? '38. a8=Q' : longLine,
					engine: 'Fixture Stockfish',
					alternatives: [
						{
							cp: root ? 20 : 150,
							mate: null,
							white_wins: null,
							best_move: root ? 'a7a8r' : 'h7g6',
							continuation: root ? '38. a8=R' : '38... Kg6'
						}
					]
				}
			}
		});
	});
	await page.goto('/games/17');
	const engineLines = page.getByRole('region', { name: 'Engine lines' });
	const first = engineLines.getByRole('group', { name: 'Best continuation' });
	const second = engineLines.getByRole('group', { name: 'Second continuation' });
	await expect(first).toHaveAttribute('title', '38. a8=Q');
	await expect(first.getByRole('img', { name: 'queen' })).toBeVisible();
	await expect(second.getByRole('img', { name: 'rook' })).toBeVisible();
	const height = (await engineLines.boundingBox())!.height;
	await page.getByRole('button', { name: 'Next move', exact: true }).click();
	await expect(first).toHaveAttribute('title', longLine);
	await expect(second).toHaveText('38... g6');
	await expect(second.getByRole('img', { name: 'king' })).toHaveAttribute('src', /\/bK\.svg$/);
	await expect(first.getByRole('img').nth(0)).toHaveAttribute('src', /\/bK\.svg$/);
	await expect(first.getByRole('img').nth(1)).toHaveAttribute('src', /\/wQ\.svg$/);
	await expect(first.getByRole('img').nth(2)).toHaveAttribute('src', /\/bK\.svg$/);
	expect((await engineLines.boundingBox())!.height).toBe(height);
	expect(await first.evaluate((row) => row.scrollWidth)).toBeGreaterThan(
		await first.evaluate((row) => row.clientWidth)
	);
	await engineLines.getByRole('button', { name: 'Play second engine move' }).click();
	await expect(
		page.getByRole('group', { name: /Chessboard/ }).getByTitle('g6: Black king')
	).toBeVisible();
});

test('keeps pending game metadata visible and refuses invalid FEN', async ({ page }) => {
	await page.route('**/api/v1/games/17/analysis*', (route) =>
		route.fulfill({
			json: {
				...gameAnalysis,
				status: 'pending',
				initial_fen: null,
				moves: [],
				legal_moves_by_ply: []
			}
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
		remarks.getByText('The pawn reaches the back rank and becomes a queen.')
	).toBeVisible();
	await expect(remarks.getByText('Move evidence', { exact: true })).toHaveCount(0);
	await expect(remarks.getByText('38...Kg6 39. Qa6+', { exact: true })).toBeHidden();
	await page.getByRole('button', { name: 'Next move', exact: true }).click();
	await expect(remarks.getByRole('heading', { name: 'Best', exact: true })).toBeVisible();
	await page.getByRole('button', { name: 'Next move', exact: true }).click();
	const blunder = remarks.getByRole('heading', { name: 'Blunder', exact: true });
	await expect(blunder).toBeVisible();
	await expect(remarks.getByText('After g6, a6+ gives check. Play g7 instead.')).toBeVisible();
	await expect(blunder).toHaveClass(/#fa412d/);
	await expect(blunder.getByText('??', { exact: true })).toBeVisible();
	await page.getByRole('button', { name: 'First position', exact: true }).click();
	await expect(remarks.getByRole('heading', { name: 'Best', exact: true })).toBeVisible();
});

test('uses piece symbols in coaching while preserving pawn moves and SAN details', async ({
	page
}) => {
	await page.route('**/api/v1/games/17/moves/2/explanation?*', (route) =>
		route.fulfill({
			json: {
				...noMoveCoaching,
				move_breakdown: {
					...noMoveCoaching.move_breakdown,
					remark: 'After exd5, Nfxe2+ gives check. Play Be2 or Qe2. The line ends with a8=R#.'
				}
			}
		})
	);
	await page.goto('/games/17?ply=2');
	const remarks = page.getByRole('region', { name: 'Move coaching' });
	await expect(
		remarks.getByText('After exd5, fxe2+ gives check. Play e2 or e2. The line ends with a8=#.')
	).toBeVisible();
	await expect(remarks.getByRole('img')).toHaveCount(4);
	const knight = remarks.getByRole('img', { name: 'knight' });
	await expect(knight).toBeVisible();
	expect(
		await knight.evaluate(
			(icon) => icon.getBoundingClientRect().height / parseFloat(getComputedStyle(icon).fontSize)
		)
	).toBeGreaterThan(1.3);
});

test('plays a variation from the review board and traces each position independently', async ({
	page
}) => {
	let releaseFirstEvaluation: () => void = () => {};
	const firstEvaluation = new Promise<void>((resolve) => (releaseFirstEvaluation = resolve));
	let failSecondEvaluation = true;

	await page.route('**/api/v1/games/17/review/variation', async (route) => {
		const request = route.request().postDataJSON();
		if (!request.line.length)
			return route.fulfill({ status: 503, json: { message: 'Engine unavailable.' } });
		expect(request.ply).toBe(1);
		expect(request.profile_hash).toBe(gameAnalysis.profile_hash);
		const length = request.line.length;
		const score = length === 1 ? 55 : 150;
		if (request.evaluate && request.line.join(' ') === 'h7g7') await firstEvaluation;
		if (request.evaluate && length === 2 && failSecondEvaluation) {
			failSecondEvaluation = false;
			return route.fulfill({ status: 503, json: { message: 'Check Stockfish and retry.' } });
		}
		const afterKing = {
			fen: 'Q7/6k1/8/8/8/8/8/7K w - - 1 39',
			side_to_move: 'white',
			legal_moves: ['a8a7'],
			san: 'Kg7'
		};
		const afterQueen = {
			fen: '8/Q5k1/8/8/8/8/8/7K b - - 2 39',
			side_to_move: 'black',
			legal_moves: ['g7h6'],
			san: 'Qa7+'
		};
		expect(length).toBeGreaterThan(0);
		const position =
			length === 2
				? afterQueen
				: request.line[0] === 'h7g7'
					? afterKing
					: { ...afterKing, fen: 'Q7/8/7k/8/8/8/8/7K w - - 1 39', san: 'Kh6' };
		return route.fulfill({
			json: {
				...position,
				outcome: null,
				evaluation: request.evaluate
					? {
							cp: score,
							mate: null,
							white_wins: null,
							best_move: position.legal_moves[0],
							continuation: length === 1 ? '39. Qa7+' : '39... Kh6',
							engine: 'Fixture Stockfish',
							alternatives: []
						}
					: null
			}
		});
	});

	await page.goto('/games/17?ply=2');
	const board = page.getByRole('group', { name: /Chessboard/ });
	const bar = page.getByRole('img', { name: /Position evaluation/ });
	const square = (coordinate: string) => board.locator(`button[data-square="${coordinate}"]`);
	await expect(square('h7')).toHaveAttribute('draggable', 'true');
	await square('h7').dragTo(square('g7'));
	await expect(square('g7')).toHaveAccessibleName(/g7: Black king/);
	await square('a8').click();
	await expect(square('a7')).toHaveAccessibleName(/Legal destination/);
	await square('a7').click();
	await expect(square('a7')).toHaveAccessibleName(/a7: White queen/);
	await expect(bar).toHaveAccessibleName('Position evaluation unavailable');
	releaseFirstEvaluation();
	await expect(
		page.getByRole('region', { name: 'Engine lines' }).getByText('Check Stockfish and retry.')
	).toBeVisible();
	await expect(bar).toHaveAccessibleName('Position evaluation unavailable');
	await page.getByRole('button', { name: 'Retry' }).click();
	await expect(bar).toHaveAccessibleName('Position evaluation: +1.50 (White perspective)');

	const graph = page.getByRole('region', { name: 'Variation evaluation' });
	await expect(graph.locator('circle')).toHaveCount(3);
	await page.getByRole('button', { name: 'Previous move' }).click();
	await expect(bar).toHaveAccessibleName('Position evaluation: +0.55 (White perspective)');
	await page.getByRole('button', { name: 'Play best move' }).click();
	await expect(bar).toHaveAccessibleName('Position evaluation: +1.50 (White perspective)');
	await page.getByRole('button', { name: 'Branch point' }).click();
	await square('h7').click();
	await square('h6').click();
	await expect(square('h6')).toHaveAccessibleName(/h6: Black king/);
	await expect(page.getByRole('button', { name: 'Qa7+' })).toHaveCount(0);
	await page
		.getByRole('table', { name: 'Move notation' })
		.getByRole('button', { name: /Kg6/ })
		.click();
	await expect(board.getByTitle('g6: Black king', { exact: true })).toBeVisible();
	await expect(bar).toHaveAccessibleName('Position evaluation: +2.10 (White perspective)');
	await expect(graph).toHaveCount(0);

	await page.getByRole('button', { name: 'Previous move' }).click();
	await square('h7').click();
	await square('g6').click();
	await expect(board.getByTitle('g6: Black king', { exact: true })).toBeVisible();
	await expect(graph).toHaveCount(0);
});

test('offers underpromotion when exploring a custom starting position', async ({ page }) => {
	await page.route('**/api/v1/games/17/review/variation', async (route) => {
		const { ply, line } = route.request().postDataJSON();
		if (!line.length)
			return route.fulfill({ status: 503, json: { message: 'Engine unavailable.' } });
		expect(ply).toBe(0);
		expect(line).toEqual(['a7a8n']);
		return route.fulfill({
			json: {
				fen: 'N7/7k/8/8/8/8/8/7K b - - 0 38',
				side_to_move: 'black',
				legal_moves: [],
				san: 'a8=N',
				outcome: '1/2-1/2',
				evaluation: {
					cp: 0,
					mate: null,
					white_wins: null,
					best_move: null,
					continuation: '',
					engine: null,
					alternatives: []
				}
			}
		});
	});
	await page.goto('/games/17');
	await page.getByRole('button', { name: 'a7: White pawn' }).click();
	await page.getByRole('button', { name: /a8: empty/ }).click();
	await page.getByRole('button', { name: 'Knight' }).click();
	await expect(page.getByRole('button', { name: /a8: White knight/ })).toBeVisible();
	await expect(page.getByText('Variation ended · 1/2-1/2')).toBeVisible();
});

test('plays an engine move when an older backend omits the second line', async ({ page }) => {
	await page.route('**/api/v1/games/17/review/variation', (route) => {
		const { ply, line, evaluate } = route.request().postDataJSON();
		expect(ply).toBe(1);
		if (line.length) expect(line).toEqual(['h7g7']);
		return route.fulfill({
			json: {
				fen: line.length ? 'Q7/6k1/8/8/8/8/8/7K w - - 1 39' : gameAnalysis.moves[0].fen_after,
				side_to_move: line.length ? 'white' : 'black',
				legal_moves: line.length ? ['a8a7', 'a8g8'] : gameAnalysis.legal_moves_by_ply[ply],
				san: line.length ? 'Kg7' : null,
				outcome: null,
				evaluation: evaluate
					? {
							cp: line.length ? 54 : 20,
							mate: null,
							white_wins: null,
							best_move: line.length ? 'a8a7' : 'h7g7',
							continuation: line.length ? '39. Qa7+' : '38... Kg7',
							engine: 'Fixture Stockfish'
						}
					: null
			}
		});
	});

	await page.goto('/games/17?ply=2');
	const engineLines = page.getByRole('region', { name: 'Engine lines' });
	await expect(
		engineLines.getByText('Restart Chess Coach to load both engine lines.')
	).toBeVisible();
	await engineLines.getByRole('button', { name: 'Play best move' }).click();
	await expect(
		page.getByRole('group', { name: /Chessboard/ }).getByTitle('g7: Black king')
	).toBeVisible();
	await expect(engineLines.getByTitle('39. Qa7+', { exact: true })).toBeVisible();
	await expect(engineLines.getByText('The backend returned an unexpected response.')).toHaveCount(
		0
	);
});
