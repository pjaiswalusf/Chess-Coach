import { expect, test } from '@playwright/test';
import { execFileSync, spawn } from 'node:child_process';
import { once } from 'node:events';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

const address = 'http://127.0.0.1:8000';

test('loads and refreshes deep links from FastAPI with real API data and Ollama offline', async ({
	page
}, info) => {
	test.skip(
		Boolean(
			process.env.PHASE16_LIVE || process.env.PHASE10_REAL || process.env.PHASE18_TRAINING_DB
		),
		'The packaged smoke test needs its own disposable server on port 8000.'
	);
	test.setTimeout(45_000);
	const root = resolve('..');
	const directory = mkdtempSync(join(tmpdir(), 'chess-coach-package-'));
	const env = {
		...process.env,
		CHESS_COACH_DATABASE_PATH: join(directory, 'packaged.db'),
		CHESS_COACH_OLLAMA_HOST: 'http://127.0.0.1:9',
		CHESS_COACH_STOCKFISH_EXECUTABLE: join(directory, 'missing-stockfish')
	};
	const errors: string[] = [];
	page.on('pageerror', (error) => errors.push(error.message));
	page.on('console', (message) => {
		if (message.type() === 'error') errors.push(message.text());
	});
	let log = '';
	try {
		execFileSync(join(root, '.venv/bin/python'), ['-m', 'alembic', 'upgrade', 'head'], {
			cwd: root,
			env
		});
		const server = spawn(join(root, 'scripts/start.sh'), { cwd: directory, env });
		const exited = once(server, 'close');
		server.stdout.on('data', (chunk) => (log += chunk.toString()));
		server.stderr.on('data', (chunk) => (log += chunk.toString()));
		try {
			// Wait for this process to bind instead of accepting another server on port 8000.
			await expect.poll(() => log).toContain('Uvicorn running on http://127.0.0.1:8000');
			const ready = await page.request.get(address + '/health/ready');
			expect(ready.status()).toBe(200);
			for (const [path, heading] of [
				['/', 'Dashboard'],
				['/games', 'Games'],
				['/coach', 'Coach'],
				['/training', 'Puzzles'],
				['/sync', 'Sync'],
				['/system', 'System'],
				['/games/analysis', 'Analyze your completed games']
			]) {
				expect((await page.goto(address + path))?.status()).toBe(200);
				await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible();
				expect((await page.reload())?.status()).toBe(200);
				await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible();
			}

			const games = page.waitForResponse(
				(response) => new URL(response.url()).pathname === '/api/v1/games'
			);
			await page.goto(address + '/games');
			const response = await games;
			expect(response.status()).toBe(200);
			expect(response.headers()['content-type']).toContain('application/json');
			expect((await response.json()).total).toBe(0);
			await expect(page.getByText('No games imported yet.')).toBeVisible();

			await page.goto(address + '/system');
			await expect(page.getByText('Degraded', { exact: true })).toBeVisible();
			await expect(page.getByText(/Start Ollama/)).toBeVisible();
			await expect(page.getByText('New AI explanations are unavailable.')).toBeVisible();
			await expect(page.getByText('Backend connected', { exact: true })).toBeVisible();
			expect(errors).toEqual([]);
		} finally {
			server.kill('SIGINT');
			const deadline = setTimeout(() => server.kill('SIGKILL'), 5_000);
			try {
				await exited;
			} finally {
				clearTimeout(deadline);
			}
		}
	} catch (error) {
		await info.attach('packaged-api.log', { body: log, contentType: 'text/plain' });
		throw error;
	} finally {
		rmSync(directory, { recursive: true, force: true });
	}
});
