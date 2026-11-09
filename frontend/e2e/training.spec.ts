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
		await route.fulfill({
			json: {
				correct: false,
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
	await page.getByRole('button', { name: 'a8: empty' }).click();
	await expect(page.getByRole('button', { name: 'Submit move' })).toBeDisabled();
	await page.getByLabel('Promote to').selectOption('a7a8n');
	await page.getByRole('button', { name: 'Submit move' }).click();
	await expect(page.getByRole('alert')).toContainText('Move submission failed');
	await expect(page.getByRole('button', { name: 'a7: White pawn' })).toBeDisabled();
	await page.getByRole('button', { name: 'Retry submission' }).click();
	await expect(page.getByText('Incorrect', { exact: true })).toBeVisible();
	await expect(page.getByText('Engine solution')).toContainText('a8=Q+');
	expect(submitted).toHaveLength(2);
	expect(submitted[1]).toEqual(submitted[0]);
	expect(submitted[0].move_uci).toBe('a7a8n');
	await page.getByRole('button', { name: 'Next puzzle' }).click();
	await expect(page.getByRole('heading', { name: 'All caught up' })).toBeVisible();
	await page.reload();
	await expect(page.getByText('1 attempt · 0 correct · 1 incorrect')).toBeVisible();
});
