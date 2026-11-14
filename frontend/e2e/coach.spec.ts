import { expect, test } from '@playwright/test';
import { patterns, noHistoricalCoaching, profile, reportHash } from './phase17-fixtures.js';

test.beforeEach(async ({ page }) => {
	await page.route('**/health', (route) => route.fulfill({ json: { status: 'ok' } }));
	await page.route('**/api/v1/system/llm', (route) =>
		route.fulfill({
			json: {
				status: 'server_unavailable',
				model: 'local-fixture',
				server_reachable: false,
				model_installed: false
			}
		})
	);
	await page.route('**/api/v1/coaching/history?*', (route) =>
		route.fulfill({ json: noHistoricalCoaching })
	);
});

test('keeps deterministic evidence and precise review links while Ollama is unavailable', async ({
	page
}) => {
	await page.route('**/api/v1/analytics/patterns?window=last_50', (route) =>
		route.fulfill({ json: patterns('last_50') })
	);
	await page.goto('/coach');
	await page.getByText('View analysis details', { exact: true }).click();
	await expect(page.getByText(/12 analyzed of 12 selected games/)).toBeVisible();
	await expect(
		page.getByText('3 significant and 12 critical errors in 120 opportunities')
	).toBeVisible();
	await expect(page.getByRole('link', { name: 'Game 17, ply 2' })).toHaveAttribute(
		'href',
		`/games/17?ply=2&profile=${profile}`
	);
	await expect(
		page.getByText(/Stockfish analysis and statistics are still available/)
	).toBeVisible();
});

test('leads with a practice priority and opens the matching puzzle', async ({ page }) => {
	await page.route('**/api/v1/analytics/patterns?window=last_50', (route) =>
		route.fulfill({
			json: {
				...patterns('last_50'),
				priority: {
					pattern: 'lost_advantage',
					title: 'Protect your advantage',
					finding: 'A sustained advantage slipped away.',
					habit: 'Check your opponent’s forcing replies.',
					affected_games: 5,
					practice_puzzle_id: 42,
					examples: [
						{
							game_id: 17,
							ply: 2,
							move_label: '1...Kg6',
							opponent: 'Alex',
							detail: 'The advantage fell.'
						},
						{
							game_id: 16,
							ply: 5,
							move_label: '3.Qd6',
							opponent: 'Robin',
							detail: 'The advantage fell.'
						}
					]
				}
			}
		})
	);
	await page.route('**/api/v1/training/next?puzzle_id=42', (route) =>
		route.fulfill({
			json: {
				puzzle: {
					id: 42,
					fen: '7k/P7/8/8/8/8/8/7K w - - 0 1',
					side_to_move: 'white',
					theme: 'forced_mate',
					difficulty: 'easy',
					legal_moves: ['a7a8q'],
					attempt_count: 0
				}
			}
		})
	);
	await page.route('**/api/v1/training/{stats,progress}', (route) =>
		route.fulfill({ status: 503 })
	);
	await page.goto('/coach');
	await expect(page.getByRole('heading', { name: 'Protect your advantage' })).toBeVisible();
	await expect(page.getByRole('link', { name: '1...Kg6 vs Alex' })).toBeVisible();
	await expect(page.getByRole('link', { name: '3.Qd6 vs Robin' })).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Measured evidence' })).toBeHidden();
	await page.getByRole('link', { name: 'Practice this' }).click();
	await expect(page).toHaveURL('/training?puzzle=42');
	await expect(page.getByRole('button', { name: 'a7: White pawn' })).toBeVisible();
});

test('does not replace the current window with an older response', async ({ page }) => {
	const old = Promise.withResolvers<void>();
	await page.route('**/api/v1/analytics/patterns?window=last_50', (route) =>
		route.fulfill({ json: patterns('last_50', 2) })
	);
	await page.route('**/api/v1/analytics/patterns?window=last_20', async (route) => {
		await old.promise;
		await route.fulfill({ json: patterns('last_20', 3) }).catch(() => {});
	});
	await page.route('**/api/v1/analytics/patterns?window=last_100', (route) =>
		route.fulfill({ json: patterns('last_100') })
	);
	try {
		await page.goto('/coach');
		await page.getByText('View analysis details', { exact: true }).click();
		await expect(page.getByText(/Not enough analyzed games or repeated errors/)).toBeVisible();
		const window = page.getByLabel('Analysis window');
		const first = page.waitForRequest('**/api/v1/analytics/patterns?window=last_20');
		await window.selectOption('last_20');
		await first;
		await window.selectOption('last_50');
		await window.selectOption('last_100');
		await expect(page.getByText(/12 analyzed of 12 selected games/)).toBeVisible();
		old.resolve();
		await expect(page).toHaveURL('/coach?window=last_100');
		await page.reload();
		await page.getByText('View analysis details', { exact: true }).click();
		await expect(window).toHaveValue('last_100');
		await expect(page.getByText(/12 analyzed of 12 selected games/)).toBeVisible();
	} finally {
		old.resolve();
	}
});

test('separates saved practice prose from measured evidence and rejects a stale report', async ({
	page
}) => {
	let matching = false;
	await page.route('**/api/v1/analytics/patterns?window=last_50', (route) =>
		route.fulfill({ json: patterns('last_50') })
	);
	await page.route('**/api/v1/coaching/history?*', (route) =>
		route.fulfill({
			json: {
				...noHistoricalCoaching,
				status: 'done',
				evidence: { report_hash: matching ? reportHash : 'different' },
				coach: {
					status: 'explained',
					summary: 'Look at endgame decisions.',
					priorities: [
						{
							pattern_id: 'phase:endgame',
							explanation: 'Review the linked position.',
							practice_tip: 'List your safe king moves.'
						}
					]
				}
			}
		})
	);
	await page.goto('/coach');
	await page.getByText('View analysis details', { exact: true }).click();
	await expect(page.getByText(/coaching evidence and measured report differ/)).toBeVisible();
	await expect(page.getByText(/List your safe king moves/)).toHaveCount(0);
	matching = true;
	await page.getByRole('button', { name: 'Refresh measured evidence' }).click();
	await expect(page.getByText(/List your safe king moves/)).toBeVisible();
	await expect(page.getByText(/3 significant and 12 critical errors/)).toBeVisible();
});
