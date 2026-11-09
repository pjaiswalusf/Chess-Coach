import { type ChildProcess, spawn } from 'node:child_process';
import { once } from 'node:events';
import { existsSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, join, resolve } from 'node:path';
import { expect, test, type Page } from '@playwright/test';

test('recovers from source and API outages, then reviews, coaches and practices from saved games', async ({
	page,
	context
}, info) => {
	test.setTimeout(75_000);
	const directory = mkdtempSync(join(tmpdir(), 'chess-coach-e2e-'));
	const root = resolve('..');
	const python = process.env.CHESS_COACH_E2E_PYTHON ?? join(root, '.venv/bin/python');
	const errors: string[] = [];
	let server: ChildProcess | undefined;
	let log = '';
	const marker = (name: string) => join(directory, name);
	const observe = (tab: Page) => tab.on('pageerror', (error) => errors.push(error.message));
	const navigate = (tab: Page, name: string) =>
		tab.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name }).click();
	observe(page);

	async function start() {
		server = spawn(python, ['tests/fixtures/phase20_app.py', directory, '8001'], {
			cwd: root,
			stdio: ['ignore', 'pipe', 'pipe']
		});
		server.on('error', (error) => (log += `${error.message}\n`));
		server.stdout?.on('data', (chunk) => (log += chunk.toString()));
		server.stderr?.on('data', (chunk) => (log += chunk.toString()));
		await expect
			.poll(async () => {
				try {
					const response = await context.request.get('/health/ready', {
						timeout: 1_000
					});
					return {
						fixture: response.headers()['x-chess-coach-fixture'],
						body: await response.json()
					};
				} catch {
					return 0;
				}
			})
			.toEqual({ fixture: basename(directory), body: { status: 'ready' } });
	}

	async function stop() {
		if (!server?.pid || server.exitCode !== null || server.signalCode !== null) return;
		const exited = once(server, 'exit');
		server.kill();
		const deadline = setTimeout(() => server?.kill('SIGKILL'), 5_000);
		try {
			await exited;
		} finally {
			clearTimeout(deadline);
		}
	}

	try {
		await start();
		await page.goto('/');
		await expect(page.getByText(/No games imported yet/)).toBeVisible();
		await navigate(page, 'Sync');
		await expect(page.getByRole('heading', { name: 'Sync', exact: true })).toBeVisible();
		await page.getByLabel('Chess.com username').fill('TestPlayer');
		const sync = page.getByRole('button', { name: 'Sync Games' });
		writeFileSync(marker('timeout'), '');
		await sync.click();
		await expect(
			page.getByText(/Chess.com could not be reached. Your saved games are safe/)
		).toBeVisible();
		rmSync(marker('timeout'));
		writeFileSync(marker('rate-limit'), '');
		await sync.click();
		await expect(page.getByText(/Chess.com is limiting requests temporarily/)).toBeVisible();
		rmSync(marker('rate-limit'));
		await sync.click();
		await expect(page.getByText(/New games: 14/)).toBeVisible();
		await expect(page.getByText(/1 game was skipped for analysis/)).toBeVisible();
		const games = await context.request.get('/api/v1/games');
		expect(games.ok()).toBeTruthy();
		expect((await games.json()).total).toBe(14);

		const accepted = page.waitForResponse(
			(response) =>
				response.url().endsWith('/api/v1/analysis-runs') && response.request().method() === 'POST'
		);
		const analyze = page.getByRole('button', { name: 'Analyze Pending Games' });
		await analyze.click();
		const run = await accepted;
		expect(run.status()).toBe(202);
		const { run_id } = await run.json();
		await expect.poll(() => existsSync(marker('analysis-paused'))).toBeTruthy();
		await expect(page.getByText(`Analysis run #${run_id}`)).toBeVisible();
		await expect(analyze).toBeDisabled();
		const progress = `/api/v1/analysis-runs/${run_id}/progress`;
		expect((await (await context.request.get(progress)).json()).status).toBe('running');
		await page.close();
		writeFileSync(marker('continue-analysis'), '');
		await expect
			.poll(async () => (await (await context.request.get(progress)).json()).status)
			.toBe('completed');

		const reopened = await context.newPage();
		observe(reopened);
		await reopened.goto('/sync');
		await expect(reopened.getByText(/Analyzed: 13/)).toBeVisible();
		await navigate(reopened, 'Games');
		await reopened.getByRole('link', { name: 'vs Fixture_13' }).click();
		await expect(reopened.getByRole('group', { name: /Chessboard/ })).toBeVisible();
		await reopened.getByRole('button', { name: '4. Ne2 — Critical error' }).click();
		await expect(reopened.getByText('Before 4. Ne2 · Ply 7')).toBeVisible();
		await expect(reopened.getByText('f3f7', { exact: true }).first()).toBeVisible();
		await expect(reopened.getByRole('img', { name: /Stockfish evaluations/ })).toBeVisible();

		await navigate(reopened, 'Coach');
		await expect(reopened.getByText(/13 analyzed of 13 selected games/)).toBeVisible();
		await reopened.getByRole('button', { name: 'Generate historical coaching' }).click();
		const advice = 'Review your opening decisions before moving.';
		await expect(reopened.getByText(advice)).toBeVisible();

		await navigate(reopened, 'Training');
		const board = reopened.getByRole('group', { name: /Chessboard/ });
		await board.locator('[data-square="f3"]').click();
		await board.locator('[data-square="f7"]').click();
		await reopened.getByRole('button', { name: 'Submit move' }).click();
		await expect(reopened.getByText('Correct', { exact: true })).toBeVisible();
		await expect(reopened.getByText(/1 attempt ·/)).toBeVisible();

		await stop();
		await reopened.goto('/');
		await expect(reopened.getByText('Backend unavailable', { exact: true })).toBeVisible();
		writeFileSync(marker('ollama-down'), '');
		await start();
		await reopened.getByRole('button', { name: 'Retry backend connection' }).click();
		await expect(reopened.getByText('Backend connected', { exact: true })).toBeVisible();
		await navigate(reopened, 'Coach');
		await expect(reopened.getByText(advice)).toBeVisible();
		expect((await (await context.request.get('/api/v1/system/llm')).json()).status).toBe(
			'server_unavailable'
		);
		await navigate(reopened, 'Training');
		await expect(reopened.getByText(/1 attempt ·/)).toBeVisible();
		expect(errors).toEqual([]);
	} catch (error) {
		await info.attach('fixture-api.log', { body: log, contentType: 'text/plain' });
		throw error;
	} finally {
		await stop();
		rmSync(directory, { recursive: true, force: true });
	}
});
