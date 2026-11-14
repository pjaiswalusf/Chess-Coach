import { expect, test } from '@playwright/test';
import { execFileSync, spawn, type ChildProcess } from 'node:child_process';
import { once } from 'node:events';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import { createServer } from 'node:net';

test('recovers in the browser after stopping and restarting real FastAPI', async ({ page }) => {
	test.skip(
		!['1', 'preview'].includes(process.env.PHASE16_LIVE ?? ''),
		'Opt-in live proxy and FastAPI verification'
	);
	test.setTimeout(45_000);

	// Fail before spawning if port 8000 already belongs to another process.
	const probe = createServer();
	probe.listen(8000, '127.0.0.1');
	await once(probe, 'listening');
	await new Promise<void>((done) => probe.close(() => done()));

	const root = resolve('..');
	const python = resolve(root, '.venv/bin/python');
	const directory = mkdtempSync(resolve(tmpdir(), 'chess-coach-phase16-'));
	const env = {
		...process.env,
		CHESS_COACH_DATABASE_PATH: resolve(directory, 'test.db'),
		CHESS_COACH_STOCKFISH_EXECUTABLE: resolve(directory, 'missing-stockfish'),
		CHESS_COACH_OLLAMA_HOST: 'http://127.0.0.1:9'
	};
	let api: ChildProcess | undefined;
	const pageErrors: string[] = [];
	const happyConsoleErrors: string[] = [];
	const failedHappyRequests: string[] = [];
	let online = true;
	page.on('pageerror', (error) => pageErrors.push(error.message));
	page.on('console', (entry) => {
		if (online && entry.type() === 'error') happyConsoleErrors.push(entry.text());
	});
	page.on('requestfailed', (request) => {
		if (online) failedHappyRequests.push(request.url());
	});

	async function start() {
		const child = spawn(
			python,
			['-m', 'uvicorn', 'chess_coach.api.app:app', '--host', '127.0.0.1', '--port', '8000'],
			{ cwd: root, env, stdio: 'ignore' }
		);
		api = child;
		await expect
			.poll(async () => {
				if (child.exitCode !== null) throw new Error('FastAPI exited during startup.');
				try {
					return (
						await page.request.get('http://127.0.0.1:8000/health', { timeout: 1000 })
					).status();
				} catch {
					return 0;
				}
			})
			.toBe(200);
	}

	async function stop() {
		if (!api || api.exitCode !== null || api.signalCode !== null) return;
		const exited = once(api, 'exit');
		api.kill();
		await exited;
		api = undefined;
	}

	try {
		execFileSync(python, ['-m', 'alembic', 'upgrade', 'head'], { cwd: root, env });
		await start();
		const origin = 'http://127.0.0.1:9999';
		const read = await page.request.get('/api/v1/games', { headers: { Origin: origin } });
		expect(read.status()).toBe(200);
		expect(read.headers()['access-control-allow-origin']).toBeUndefined();
		const write = await page.request.post('/api/v1/sync-runs', {
			headers: { Origin: origin },
			data: {}
		});
		expect(write.status()).toBe(403);
		expect((await write.json()).code).toBe('ORIGIN_NOT_ALLOWED');
		await page.goto('/');
		await expect(page.getByText('Backend connected', { exact: true })).toBeVisible();
		const nav = page.getByRole('navigation');
		for (const name of ['Sync', 'Games', 'Coach', 'Puzzles', 'System', 'Dashboard']) {
			await nav.getByRole('link', { name, exact: true }).click();
			await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
			if (name === 'Games') await expect(page.getByText('No games imported yet.')).toBeVisible();
			if (name === 'System') {
				await expect(page.getByText('Degraded', { exact: true })).toBeVisible();
				await expect(page.getByText(/Start Ollama/)).toBeVisible();
				await expect(
					page.getByText('Install Stockfish or check the configured executable.')
				).toBeVisible();
				await expect(page.getByText('No finished analysis runs.')).toBeVisible();
				await expect(page.getByText('Games stored').locator('..').locator('dd')).toHaveText('0');
			}
		}
		await nav.getByRole('link', { name: 'Games' }).click();
		await expect(page.getByText('No games imported yet.')).toBeVisible();
		await page.reload();
		await expect(page.getByText('No games imported yet.')).toBeVisible();
		await expect(page.getByText('Backend connected', { exact: true })).toBeVisible();

		online = false;
		await stop();
		await page.getByRole('button', { name: 'Check connection' }).click();
		await expect(page.getByText('Backend unavailable', { exact: true })).toBeVisible();
		await nav.getByRole('link', { name: 'Sync' }).click();
		await expect(page.getByRole('heading', { name: 'Sync', exact: true })).toBeVisible();
		await nav.getByRole('link', { name: 'Games' }).click();
		await expect(page.getByRole('alert')).toContainText('Unable to load games.');

		await start();
		online = true;
		await page.getByRole('button', { name: 'Retry backend connection' }).click();
		await expect(page.getByText('Backend connected', { exact: true })).toBeVisible();
		await page.getByRole('button', { name: 'Retry', exact: true }).click();
		await expect(page.getByText('No games imported yet.')).toBeVisible();
		expect(pageErrors).toEqual([]);
		expect(happyConsoleErrors).toEqual([]);
		expect(failedHappyRequests).toEqual([]);
	} finally {
		await stop();
		rmSync(directory, { recursive: true, force: true });
	}
});
