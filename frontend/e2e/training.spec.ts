import { expect, test } from '@playwright/test';
import type { SubmitAttempt } from '../src/lib/api/training.js';

test('reuses the submission ID when the first response is lost and displays the server grade', async ({
	page
}) => {
	const submitted: SubmitAttempt[] = [];
	const puzzle = {
		id: 1,
		fen: '7k/P7/8/8/8/8/8/7K w - - 0 1',
		side_to_move: 'white',
		theme: 'forced_mate',
		difficulty: 'easy',
		attempt_count: 0,
		legal_moves: ['a7a8q', 'a7a8n']
	};
	await page.route('**/health', (route) => route.fulfill({ json: { status: 'ok' } }));
	await page.route('**/api/v1/training/next', (route) =>
		route.fulfill({ json: { puzzle: submitted.length ? null : puzzle } })
	);
	await page.route('**/api/v1/training/progress', (route) =>
		route.fulfill({ json: { first_attempt_at: null, cohorts: [] } })
	);
	await page.route('**/api/v1/training/stats', (route) =>
		route.fulfill({
			json: {
				puzzles_total: 1,
				puzzles_attempted: submitted.length ? 1 : 0,
				attempts_total: submitted.length ? 1 : 0,
				correct_attempts: 0,
				incorrect_attempts: submitted.length ? 1 : 0,
				accuracy: submitted.length ? 0 : null,
				puzzles_due: submitted.length ? 0 : 1,
				average_attempts: submitted.length ? 1 : null,
				themes: []
			}
		})
	);
	await page.route('**/api/v1/training/1/attempts', async (route) => {
		submitted.push(route.request().postDataJSON() as SubmitAttempt);
		if (submitted.length === 1) return route.abort();
		if (submitted.length === 3) {
			return route.fulfill({
				json: {
					correct: true,
					solution_san: 'a8=Q+',
					solution_pv_san: ['a8=Q+'],
					source_game_id: 2,
					source_ply: 18,
					source_profile_hash: 'a'.repeat(64),
					next_review_at: '2026-11-10T12:00:00Z'
				}
			});
		}
		await route.fulfill({
			json: {
				correct: false,
				attempt_id: 82,
				wrong_move_reason: 'Underpromotion misses the verified tactic.',
				solution_move_uci: 'a7a8q',
				solution_san: 'a8=Q+',
				solution_pv_san: ['a8=Q+'],
				source_game_id: 2,
				source_ply: 18,
				source_profile_hash: 'a'.repeat(64),
				next_review_at: '2026-11-10T12:00:00Z'
			}
		});
	});

	await page.goto('/training');
	await expect(page.getByRole('heading', { name: 'white to move' })).toBeVisible();
	await expect(page.getByText('Engine solution')).toHaveCount(0);
	await page.getByRole('button', { name: 'a7: White pawn' }).click();
	await page.getByRole('button', { name: /a8: empty/ }).click();
	await page.getByLabel('Promote to').selectOption('a7a8n');
	await expect(page.getByRole('alert')).toContainText('Move submission failed');
	await expect(page.getByRole('button', { name: 'a7: White pawn' })).toBeDisabled();
	await page.getByRole('button', { name: 'Retry submission' }).click();
	await expect(page.getByText('Incorrect', { exact: true })).toBeVisible();
	await expect(page.getByText('Underpromotion misses the verified tactic.')).toBeVisible();
	await expect(page.getByText('0 solved in a row')).toBeVisible();
	await page.getByRole('button', { name: 'Retry puzzle' }).click();
	await expect(page.getByRole('button', { name: 'a7: White pawn' })).toBeEnabled();
	expect(submitted).toHaveLength(2);
	expect(submitted[1]).toEqual(submitted[0]);
	expect(submitted[0].move_uci).toBe('a7a8n');
	await page.getByRole('button', { name: 'a7: White pawn' }).click();
	await page.getByRole('button', { name: /a8: empty/ }).click();
	await page.getByLabel('Promote to').selectOption('a7a8q');
	await expect(page.getByText('Correct', { exact: true })).toBeVisible();
	expect(submitted[2]).toMatchObject({ move_uci: 'a7a8q', retry_after_attempt_id: 82 });
	await page.getByRole('button', { name: 'Next puzzle' }).click();
	await expect(page.getByRole('heading', { name: 'All caught up' })).toBeVisible();
	await page.reload();
	await expect(page.getByText('1 attempt · 0 correct · 1 incorrect')).toBeVisible();
});

test('plays the opponent reply and asks for the second move before grading', async ({ page }) => {
	const puzzle = {
		id: 2,
		fen: 'rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2',
		side_to_move: 'white',
		theme: 'material_gain',
		difficulty: 'hard',
		attempt_count: 0,
		solver_moves: 2,
		legal_moves: ['e4d5']
	};
	await page.route('**/health', (route) => route.fulfill({ json: { status: 'ok' } }));
	await page.route('**/api/v1/training/next', (route) => route.fulfill({ json: { puzzle } }));
	await page.route('**/api/v1/training/progress', (route) =>
		route.fulfill({ json: { first_attempt_at: null, cohorts: [] } })
	);
	await page.route('**/api/v1/training/stats', (route) =>
		route.fulfill({ json: { puzzles_total: 1, puzzles_due: 1, attempts_total: 0, themes: [] } })
	);
	await page.route('**/api/v1/training/2/play', async (route) => {
		const { moves } = route.request().postDataJSON();
		if (moves.length === 1) {
			expect(moves).toEqual(['e4d5']);
			return route.fulfill({
				json: {
					continuation: {
						fen: 'r1bqkbnr/ppp1pppp/2n5/3P4/8/8/PPPP1PPP/RNBQKBNR w KQkq - 1 3',
						legal_moves: ['d5c6'],
						reply_san: 'Nc6'
					}
				}
			});
		}
		expect(moves).toEqual(['e4d5', 'd5c6']);
		return route.fulfill({
			json: {
				result: {
					correct: true,
					solution_san: 'exd5',
					solution_pv_san: ['exd5', 'Nc6', 'dxc6', 'bxc6'],
					source_game_id: 2,
					source_ply: 3,
					source_profile_hash: 'a'.repeat(64),
					next_review_at: '2026-11-17T12:00:00Z',
					final_fen: 'r1bqkbnr/p1p1pppp/2p5/8/8/8/PPPP1PPP/RNBQKBNR w KQkq - 0 4'
				}
			}
		});
	});
	await page.goto('/training');
	await expect(page.getByText('Move 1 of 2')).toBeVisible();
	await page.locator('[data-square="e4"]').click();
	await page.locator('[data-square="d5"]').click();
	await expect(page.getByText(/Opponent played Nc6. Move 2 of 2/)).toBeVisible();
	await expect(page.getByText('Engine solution')).toHaveCount(0);
	await page.locator('[data-square="d5"]').click();
	await page.locator('[data-square="c6"]').click();
	await expect(page.getByText('Correct', { exact: true })).toBeVisible();
	await expect(page.getByRole('button', { name: 'c6: Black pawn' })).toBeVisible();
});
