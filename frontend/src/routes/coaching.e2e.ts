import { expect, test } from '@playwright/test';

const base = {
	job_id: 1,
	status: 'not_generated',
	evidence: {},
	coach: null,
	error_code: null,
	message: null,
	cached: false
};

for (const outcome of ['done', 'failed', 'insufficient_evidence', 'unavailable']) {
	test(`move coaching: ${outcome}`, async ({ page }) => {
		let generated = 0;
		await page.route('**/api/v1/analysis-worker', (route) =>
			route.fulfill({
				json: { available: false, database: 'healthy', players: [], engine_version: 'Fixture' }
			})
		);
		await page.route('**/api/v1/analysis-runs', (route) =>
			route.fulfill({
				json: [
					{
						id: 1,
						status: 'completed',
						games_total: 1,
						games_completed: 1,
						games_failed: 0,
						games_skipped: 0,
						games_excluded: 0,
						progress_percent: 100,
						positions_analyzed: 5,
						cache_hits: 0,
						engine_version: 'Fixture',
						engine_config_json: { nodes: 10000 },
						profile_hash: 'fixture',
						games: [{ game_id: 1, status: 'done' }]
					}
				]
			})
		);
		await page.route('**/api/v1/games/1/analysis?*', (route) =>
			route.fulfill({
				json: {
					moves: [
						{
							ply: 1,
							played_move_san: 'e4',
							best_move_uci: 'd2d4',
							mate_after_white: null,
							eval_after_cp_white: 20,
							loss_cp: 30
						}
					]
				}
			})
		);
		const coach = {
			status: 'explained',
			summary: '<script>unsafe()</script>',
			what_went_wrong: 'Fixture cause.',
			why_best_move_works: 'Fixture alternative.',
			lesson: 'Inspect the position.',
			practice_tip: 'Review the line.'
		};
		const result = {
			...base,
			status: outcome,
			coach:
				outcome === 'done'
					? coach
					: outcome === 'insufficient_evidence'
						? { status: 'insufficient_evidence', summary: 'More evidence is needed.' }
						: null,
			message: outcome === 'failed' ? 'Coaching failed. Retry.' : null,
			error_code: outcome === 'failed' ? 'INVALID_MODEL_OUTPUT' : null
		};
		await page.route('**/api/v1/games/1/moves/1/explanation?*', async (route) => {
			if (route.request().method() === 'POST') {
				generated++;
				if (outcome === 'unavailable')
					return route.fulfill({
						status: 503,
						json: { message: 'Start Ollama locally and retry.' }
					});
				return route.fulfill({ status: 202, json: { ...base, status: 'queued' } });
			}
			return route.fulfill({
				json: generated && outcome === 'done' ? { ...result, cached: true } : base
			});
		});
		await page.route('**/api/v1/coaching-jobs/1', (route) => route.fulfill({ json: result }));
		await page.goto('/');
		await page.getByText('Games and evidence').click();
		await page.getByRole('button', { name: 'View moves for game 1' }).click();
		await page.getByRole('button', { name: 'Explain ply 1' }).click();
		await expect(page.getByText('No explanation generated yet.')).toBeVisible();
		await page.getByRole('button', { name: 'Explain this move' }).click();
		if (outcome === 'done') {
			await expect(page.getByText('<script>unsafe()</script>', { exact: true })).toBeVisible();
			expect(await page.locator('section[aria-label="Move coaching"] script').count()).toBe(0);
			await page.reload();
			await page.getByText('Games and evidence').click();
			await page.getByRole('button', { name: 'View moves for game 1' }).click();
			await page.getByRole('button', { name: 'Explain ply 1' }).click();
			await expect(page.getByText('Inspect the position.', { exact: false })).toBeVisible();
			expect(generated).toBe(1);
		} else if (outcome === 'insufficient_evidence')
			await expect(page.getByText('More evidence is needed.')).toBeVisible();
		else
			await expect(page.getByRole('alert')).toContainText(
				outcome === 'failed' ? 'Coaching failed.' : 'Start Ollama'
			);
	});
}
