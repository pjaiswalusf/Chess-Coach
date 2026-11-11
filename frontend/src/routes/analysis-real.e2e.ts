/** Opt-in: PHASE10_REAL=1 pnpm test:e2e analysis-real.e2e.ts.
 * Requires local Stockfish. Uses a newly migrated deterministic fixture database.
 */
import { expect, test } from '@playwright/test';
import { spawn, execFileSync, type ChildProcess } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, resolve } from 'node:path';
import { once } from 'node:events';

test('real UI, API and worker survive hard stop and profile change', async ({
	page,
	context
}, testInfo) => {
	test.skip(process.env.PHASE10_REAL !== '1', 'Opt-in local Stockfish integration');
	test.setTimeout(120000);
	const root = resolve('..');
	const python = resolve(root, '.venv/bin/python');
	const cli = resolve(root, '.venv/bin/chess-coach');
	const directory = mkdtempSync(resolve(tmpdir(), 'phase17-browser-'));
	const fixture = basename(directory);
	const database = resolve(directory, 'test.db');
	execFileSync(python, ['tests/fixtures/prepare_browser_analysis.py', database], {
		cwd: root,
		stdio: 'pipe'
	});
	const env = {
		...process.env,
		CHESS_COACH_DATABASE_PATH: database,
		CHESS_COACH_STOCKFISH_NODES: '10000',
		CHESS_COACH_OLLAMA_HOST: 'http://127.0.0.1:9',
		CHESS_COACH_LLM_KEEP_ALIVE: '0'
	};
	const api = spawn(
		python,
		[
			'-m',
			'uvicorn',
			'chess_coach.api.app:app',
			'--host',
			'127.0.0.1',
			'--port',
			'8000',
			'--header',
			`X-Chess-Coach-Fixture:${fixture}`
		],
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
		expect(result.headers()['x-chess-coach-fixture']).toBe(fixture);
		return result.json();
	}
	async function workerAvailable() {
		try {
			const response = await context.request.get('/api/v1/analysis-worker');
			return (
				response.headers()['x-chess-coach-fixture'] === fixture && (await response.json()).available
			);
		} catch {
			return false;
		}
	}
	try {
		worker = spawn(cli, ['analysis-worker', '--with-coaching'], {
			cwd: root,
			env,
			stdio: 'ignore'
		});
		await expect.poll(workerAvailable, { timeout: 15000 }).toBe(true);
		await page.goto('/sync');
		await page.getByRole('button', { name: 'Analyze Pending Games' }).click({ timeout: 10000 });
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
		worker = spawn(cli, ['analysis-worker', '--with-coaching'], {
			cwd: root,
			env,
			stdio: 'ignore'
		});
		const reopened = await context.newPage();
		await reopened.goto('/sync');
		await expect.poll(async () => (await runs())[0]?.status, { timeout: 30000 }).toBe('completed');
		await expect(reopened.getByText('Analysis run #1', { exact: true })).toBeVisible();
		await expect(reopened.getByText(/Analyzed: 10/)).toBeVisible();
		const overview = await (
			await context.request.get('http://127.0.0.1:8000/api/v1/analytics/overview')
		).json();
		expect(overview.health.analyzed_games).toBe(10);
		expect(
			overview.phases.some(
				(phase: { key: string; evidence_status: string }) =>
					phase.key !== 'unclassified' && phase.evidence_status === 'sufficient'
			)
		).toBe(true);
		await reopened.getByRole('button', { name: 'Analyze Pending Games' }).click({ timeout: 10000 });
		await expect.poll(async () => (await runs())[0]?.id).toBe(2);
		const repeat = (await runs())[0];
		expect(repeat.games_skipped).toBe(10);
		expect(repeat.positions_analyzed).toBe(0);
		await expect(reopened.getByText('No pending games were eligible for analysis.')).toBeVisible();
		await stop(worker);
		worker = null;
		worker = spawn(cli, ['analysis-worker', '--with-coaching'], {
			cwd: root,
			env: { ...env, CHESS_COACH_STOCKFISH_NODES: '20000' },
			stdio: 'ignore'
		});
		await expect.poll(workerAvailable).toBe(true);
		await reopened.getByRole('button', { name: 'Analyze Pending Games' }).click({ timeout: 10000 });
		await expect.poll(async () => (await runs())[0]?.id).toBe(3);
		await expect.poll(async () => (await runs())[0]?.status, { timeout: 30000 }).toBe('completed');
		const changed = (await runs())[0];
		expect(changed.profile_hash).not.toBe(repeat.profile_hash);
		expect(changed.games_skipped).toBe(0);
		expect(changed.games_completed).toBe(10);
		await expect(reopened.getByText('Analysis run #3', { exact: true })).toBeVisible();
		await reopened.goto(`/games/${changed.games[0].game_id}`);
		await expect(reopened.getByRole('group', { name: /Chessboard/ })).toBeVisible();
		await reopened.getByRole('button', { name: 'Final position' }).click({ timeout: 10000 });
		await expect(reopened.getByRole('button', { name: 'Next move' })).toBeDisabled();
		await expect(reopened.getByRole('region', { name: 'Move coaching' })).toBeVisible();
		await reopened.screenshot({
			path: testInfo.outputPath('analysis-browser.png'),
			fullPage: true
		});
	} finally {
		await stop(worker);
		await stop(api);
		rmSync(directory, { recursive: true, force: true });
	}
});
