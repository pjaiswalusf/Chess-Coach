import { type ChildProcess, spawn } from 'node:child_process';
import { once } from 'node:events';
import { existsSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, join, resolve } from 'node:path';
import { expect, test, type Locator, type Page } from '@playwright/test';

const demo = process.env.CI ? undefined : process.env.CHESS_COACH_DEMO_DIR;
if (demo) {
	test.use({
		video: 'on',
		viewport: { width: 1280, height: 900 },
		launchOptions: { slowMo: 150 }
	});
}

test('recovers from source and API outages, then reviews, coaches and practices from saved games', async ({
	page,
	context
}, info) => {
	test.setTimeout(demo ? 150_000 : 75_000);
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
	async function holdDemoFrame(focus: Locator) {
		if (!demo) return;
		await focus.scrollIntoViewIfNeeded();
		// Give viewers time to read the recording after the state has been verified.
		await new Promise((resolve) => setTimeout(resolve, 5_000));
	}
	async function capture(tab: Page, name: string, focus: Locator) {
		if (!demo) return;
		await tab.screenshot({ path: join(demo, `${name}.png`), fullPage: true });
		await holdDemoFrame(focus);
	}
	observe(page);

	async function start() {
		const env = Object.fromEntries(
			Object.entries(process.env).filter(([key]) => !key.startsWith('CHESS_COACH_'))
		);
		server = spawn(python, [join(root, 'tests/fixtures/phase20_app.py'), directory, '8001'], {
			cwd: directory,
			env,
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
		await expect.poll(() => existsSync(marker('analysis-paused'))).toBeTruthy();
		const latest = await context.request.get('/api/v1/sync-runs/latest-work');
		const { analysis_run_id } = await latest.json();
		expect(analysis_run_id).toBeGreaterThan(0);
		await expect(page.getByText(`Analysis run #${analysis_run_id}`)).toBeVisible();
		await expect(page.getByRole('button', { name: 'Analyze Pending Games' })).toBeDisabled();
		await holdDemoFrame(page.getByText(`Analysis run #${analysis_run_id}`));
		const progress = `/api/v1/analysis-runs/${analysis_run_id}/progress`;
		expect((await (await context.request.get(progress)).json()).status).toBe('running');
		if (!demo) await page.close();
		writeFileSync(marker('continue-analysis'), '');
		await expect
			.poll(async () => (await (await context.request.get(progress)).json()).status)
			.toBe('completed');

		const reopened = demo ? page : await context.newPage();
		if (!demo) observe(reopened);
		await reopened.goto('/sync');
		await expect(reopened.getByText(/Analyzed: 13/)).toBeVisible();
		await reopened.getByRole('button', { name: 'Sync Games' }).click();
		await expect(reopened.getByText(/New games: 0/)).toBeVisible();
		expect((await (await context.request.get('/api/v1/games')).json()).total).toBe(14);
		await navigate(reopened, 'Games');
		await reopened.getByRole('link', { name: 'vs Fixture_13' }).click();
		await expect(reopened.getByRole('group', { name: /Chessboard/ })).toBeVisible();
		await reopened.getByRole('button', { name: '4. Ne2 — Blunder' }).click();
		await expect(reopened.getByText('Before 4. Ne2 · Ply 7')).toBeVisible();
		const engineLines = reopened.getByRole('region', { name: 'Engine lines' });
		await expect(engineLines.getByRole('group', { name: 'Best continuation' })).toBeVisible();
		await expect(reopened.getByRole('img', { name: /Stockfish evaluations/ })).toBeVisible();
		const moveCoaching = reopened.getByRole('region', { name: 'Move coaching' });
		await expect(
			moveCoaching.getByRole('heading', { name: /^(Blunder|Mistake|Miss)$/ })
		).toBeVisible();
		await expect(moveCoaching.getByRole('button', { name: 'Get a practice tip' })).toHaveCount(0);
		await capture(reopened, 'game-review', reopened.getByRole('region', { name: 'Move coaching' }));

		await navigate(reopened, 'Coach');
		await reopened.getByText('View analysis details', { exact: true }).click();
		await expect(reopened.getByText(/13 analyzed of 13 selected games/)).toBeVisible();
		await reopened.getByRole('button', { name: 'Generate historical coaching' }).click();
		const advice = 'Review your opening decisions before moving.';
		await expect(reopened.getByText(advice)).toBeVisible();
		await capture(reopened, 'coaching', reopened.getByText(advice));

		await navigate(reopened, 'Puzzles');
		const board = reopened.getByRole('group', { name: /Chessboard/ });
		await board.locator('[data-square="f3"]').click();
		await board.locator('[data-square="f7"]').click();
		await expect(reopened.getByText('Correct', { exact: true })).toBeVisible();
		await expect(reopened.getByText(/1 attempt ·/)).toBeVisible();
		await capture(reopened, 'training', reopened.getByText('Correct', { exact: true }));

		if (demo) {
			await navigate(reopened, 'Dashboard');
			await expect(reopened.getByText(/13 analyzed of 13 selected games/)).toBeVisible();
			await capture(
				reopened,
				'dashboard',
				reopened.getByRole('heading', { name: 'Performance by phase' })
			);
			await navigate(reopened, 'System');
			await expect(reopened.getByRole('heading', { name: 'Local services' })).toBeVisible();
			await capture(reopened, 'system', reopened.getByRole('heading', { name: 'Local services' }));
		}

		await stop();
		await reopened.goto('/');
		await expect(reopened.getByText('Backend unavailable', { exact: true })).toBeVisible();
		writeFileSync(marker('ollama-down'), '');
		await start();
		await reopened.getByRole('button', { name: 'Retry backend connection' }).click();
		await expect(reopened.getByText('Backend connected', { exact: true })).toBeVisible();
		await navigate(reopened, 'Coach');
		await reopened.getByText('View analysis details', { exact: true }).click();
		await expect(reopened.getByText(advice)).toBeVisible();
		expect((await (await context.request.get('/api/v1/system/llm')).json()).status).toBe(
			'server_unavailable'
		);
		await navigate(reopened, 'Puzzles');
		await expect(reopened.getByText(/1 attempt ·/)).toBeVisible();
		expect(errors).toEqual([]);
		if (demo) {
			const video = reopened.video();
			if (!video) throw new Error('Fixture video recording was unavailable.');
			await reopened.close();
			await video.saveAs(join(demo, 'workflow.webm'));
		}
	} catch (error) {
		await info.attach('fixture-api.log', { body: log, contentType: 'text/plain' });
		throw error;
	} finally {
		await stop();
		rmSync(directory, { recursive: true, force: true });
	}
});
