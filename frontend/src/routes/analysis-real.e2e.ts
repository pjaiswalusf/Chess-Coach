/** Opt-in: PHASE10_REAL=1 pnpm test:e2e analysis-real.e2e.ts.
 * Requires local Stockfish and the documented preflight backup; never touches the source DB.
 */
import { expect, test } from '@playwright/test';
import { spawn, execFileSync, type ChildProcess } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import { once } from 'node:events';

test('real UI, API and worker survive hard stop and profile change', async ({ page, context }) => {
	test.skip(process.env.PHASE10_REAL !== '1', 'Opt-in local Stockfish integration');
	test.setTimeout(120000);
	const root = resolve('..');
	const python = resolve(root, '.venv/bin/python');
	const database = resolve(mkdtempSync(resolve(tmpdir(), 'phase10-browser-')), 'test.db');
	execFileSync(
		python,
		['scripts/benchmark_phase10.py', '--games', '10', '--database', database, '--prepare-only'],
		{ cwd: root, stdio: 'pipe' }
	);
	const env = { ...process.env, CHESS_COACH_DATABASE_PATH: database };
	const api = spawn(
		python,
		['-m', 'uvicorn', 'chess_coach.api.app:app', '--host', '127.0.0.1', '--port', '8000'],
		{ cwd: root, env, stdio: 'ignore' }
	);
	let worker: ChildProcess | null = null;
	async function stop(child: ChildProcess | null, signal: NodeJS.Signals = 'SIGTERM') {
		if (child && child.exitCode === null && child.signalCode === null) {
			const ended = once(child, 'exit');
			child.kill(signal);
			await ended;
		}
	}
	async function runs() {
		const result = await context.request.get('http://127.0.0.1:8000/api/v1/analysis-runs');
		return result.json();
	}
	try {
		worker = spawn(python, ['-m', 'chess_coach.analysis_worker'], {
			cwd: root,
			env,
			stdio: 'ignore'
		});
		await expect
			.poll(
				async () => {
					try {
						return (
							await (
								await context.request.get('http://127.0.0.1:8000/api/v1/analysis-worker')
							).json()
						).available;
					} catch {
						return false;
					}
				},
				{ timeout: 15000 }
			)
			.toBe(true);
		await page.goto('/');
		await page.getByRole('button', { name: 'Analyze eligible games' }).click();
		await expect
			.poll(async () => (await runs())[0]?.games_completed ?? 0, {
				intervals: [20],
				timeout: 15000
			})
			.toBeGreaterThanOrEqual(2);
		await stop(worker, 'SIGKILL');
		worker = null;
		const interrupted = (await runs())[0];
		expect(interrupted.games_completed).toBeGreaterThanOrEqual(2);
		expect(interrupted.games_completed).toBeLessThan(10);
		await page.close();
		worker = spawn(python, ['-m', 'chess_coach.analysis_worker'], {
			cwd: root,
			env,
			stdio: 'ignore'
		});
		const reopened = await context.newPage();
		await reopened.goto('/');
		await expect.poll(async () => (await runs())[0]?.status, { timeout: 30000 }).toBe('done');
		await expect(reopened.getByRole('heading', { name: 'Run #1 · done' })).toBeVisible();
		await reopened.getByRole('button', { name: 'Analyze eligible games' }).click();
		await expect.poll(async () => (await runs())[0]?.id).toBe(2);
		const repeat = (await runs())[0];
		expect(repeat.games_skipped).toBe(10);
		expect(repeat.positions_analyzed).toBe(0);
		await stop(worker);
		worker = null;
		worker = spawn(python, ['-m', 'chess_coach.analysis_worker'], {
			cwd: root,
			env: { ...env, CHESS_COACH_STOCKFISH_NODES: '20000' },
			stdio: 'ignore'
		});
		await expect
			.poll(
				async () =>
					(await (await context.request.get('http://127.0.0.1:8000/api/v1/analysis-worker')).json())
						.available
			)
			.toBe(true);
		await reopened.getByRole('button', { name: 'Analyze eligible games' }).click();
		await expect.poll(async () => (await runs())[0]?.id).toBe(3);
		await expect.poll(async () => (await runs())[0]?.status, { timeout: 30000 }).toBe('done');
		const changed = (await runs())[0];
		expect(changed.profile_hash).not.toBe(repeat.profile_hash);
		expect(changed.games_skipped).toBe(0);
		expect(changed.games_completed).toBe(10);
		await expect(reopened.getByRole('heading', { name: 'Run #3 · done' })).toBeVisible();
		await reopened.screenshot({ path: resolve(root, 'data/phase10-browser.png'), fullPage: true });
		const newest = reopened
			.locator('article')
			.filter({ has: reopened.getByRole('heading', { name: 'Run #3 · done' }) });
		await newest.getByText('Games and evidence').click();
		await newest
			.getByRole('button', { name: /View moves for game/ })
			.first()
			.click();
		await expect(reopened.getByRole('table')).toBeVisible();
	} finally {
		await stop(worker);
		await stop(api);
	}
});
