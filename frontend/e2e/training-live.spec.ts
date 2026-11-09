import { execFileSync, spawn, type ChildProcess } from 'node:child_process';
import { once } from 'node:events';
import { mkdtempSync, rmSync } from 'node:fs';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import { expect, test } from '@playwright/test';
import type {
	AttemptResult,
	PublicPuzzle,
	SubmitAttempt,
	TrainingStats
} from '../src/lib/api/training.js';

test('solves real historical puzzles, restarts FastAPI, and replays a committed submission', async ({
	page
}, info) => {
	const source = process.env.PHASE18_TRAINING_DB;
	test.skip(!source, 'Supply a migrated database with two new puzzles for one tracked player.');
	test.setTimeout(45_000);
	const root = resolve('..');
	const python = resolve(root, '.venv/bin/python');
	const probe = createServer();
	probe.listen(8000, '127.0.0.1');
	await once(probe, 'listening');
	await new Promise<void>((done) => probe.close(() => done()));

	const directory = mkdtempSync(resolve(tmpdir(), 'chess-coach-phase18-'));
	const database = resolve(directory, 'test.db');
	const env = {
		...process.env,
		CHESS_COACH_DATABASE_PATH: database,
		CHESS_COACH_STOCKFISH_EXECUTABLE: resolve(directory, 'missing-stockfish'),
		CHESS_COACH_OLLAMA_HOST: 'http://127.0.0.1:9'
	};
	let api: ChildProcess | undefined;
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
					return (await page.request.get('/health', { timeout: 500 })).status();
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

	const db = (statement: string) =>
		execFileSync(
			python,
			[
				'-c',
				'import sqlite3, sys; from pathlib import Path; db = sqlite3.connect(Path(sys.argv[1]).resolve().as_uri() + "?mode=ro", uri=True); print("|".join(map(str, db.execute(sys.argv[2]).fetchone())))',
				database,
				statement
			],
			{ encoding: 'utf8' }
		).trim();
	async function next(): Promise<PublicPuzzle> {
		const response = await page.request.get('/api/v1/training/next');
		expect(response.status()).toBe(200);
		const { puzzle } = await response.json();
		expect(puzzle, 'The fixture must have a due puzzle for the tracked player.').toBeTruthy();
		return puzzle;
	}

	async function selectMove(move: string) {
		const board = page.getByRole('group', { name: /Chessboard/ });
		await board.locator(`[data-square="${move.slice(0, 2)}"]`).click();
		await board.locator(`[data-square="${move.slice(2, 4)}"]`).click();
		if (move.length === 5) await page.getByLabel('Promote to').selectOption(move);
	}

	try {
		execFileSync(python, [
			'-c',
			'import sqlite3, sys; from pathlib import Path; sqlite3.connect(Path(sys.argv[1]).resolve().as_uri() + "?mode=ro", uri=True).backup(sqlite3.connect(sys.argv[2]))',
			resolve(source!),
			database
		]);
		await start();
		const practice = await next();
		expect(practice).not.toHaveProperty('solution_move_uci');
		expect(practice).not.toHaveProperty('solution_pv_json');
		const firstMove = db(`SELECT solution_uci FROM puzzles WHERE id = ${practice.id}`);
		const firstPath = `/api/v1/training/${practice.id}/attempts`;
		const initial: TrainingStats = await (await page.request.get('/api/v1/training/stats')).json();
		await page.goto('/training');
		await expect(page.getByRole('group', { name: /Chessboard/ })).toBeVisible();
		await expect(page.getByRole('heading', { name: 'Puzzle activity' })).toBeVisible();
		await page.screenshot({ path: info.outputPath('puzzle-before.png'), fullPage: true });

		let submission: SubmitAttempt | undefined;
		let grade: AttemptResult | undefined;
		await page.route(
			'**' + firstPath,
			async (route) => {
				submission = route.request().postDataJSON() as SubmitAttempt;
				const response = await route.fetch();
				expect(response.status()).toBe(200);
				grade = (await response.json()) as AttemptResult;
				await route.abort();
			},
			{ times: 1 }
		);
		await selectMove(firstMove);
		await page.getByRole('button', { name: 'Submit move' }).click();
		await expect(page.getByRole('alert')).toContainText('Move submission failed');
		await page.getByRole('button', { name: 'Retry submission' }).click();
		await expect(page.getByText('Correct', { exact: true })).toBeVisible();
		await expect(page.getByText('Next review')).toBeVisible();
		const sourceGame = await page.request.get(
			`/api/v1/games/${grade!.source_game_id}/analysis?profile_hash=${grade!.source_profile_hash}`
		);
		expect(sourceGame.status()).toBe(200);
		await expect(page.getByRole('link', { name: /Review source game/ })).toHaveAttribute(
			'href',
			new RegExp(`ply=${grade!.source_ply}&profile=${grade!.source_profile_hash}`)
		);
		await page.screenshot({ path: info.outputPath('puzzle-correct.png'), fullPage: true });
		expect(db(`SELECT count(*) FROM puzzle_attempts WHERE puzzle_id = ${practice.id}`)).toBe('1');

		await stop();
		await start();
		const replay = await page.request.post(firstPath, { data: submission });
		expect(replay.status()).toBe(200);
		expect(await replay.json()).toEqual(grade);
		const persisted = db(
			`SELECT p.correct_streak, p.next_review_at = a.next_review_at_after FROM puzzles p JOIN puzzle_attempts a ON a.puzzle_id = p.id WHERE p.id = ${practice.id}`
		);
		expect(persisted).toBe('1|1');
		await page.reload();
		await expect(
			page.getByText(new RegExp(`${initial.attempts_total + 1} attempts? ·`))
		).toBeVisible();

		const second = await next();
		const wrong = db(`SELECT original_move_uci FROM puzzles WHERE id = ${second.id}`);
		await selectMove(wrong);
		await page.getByRole('button', { name: 'Submit move' }).click();
		await expect(page.getByText('Incorrect', { exact: true })).toBeVisible();
		await page.screenshot({ path: info.outputPath('puzzle-incorrect.png'), fullPage: true });
		await expect(
			page.getByText(new RegExp(`${initial.attempts_total + 2} attempts? ·`))
		).toBeVisible();
		await page.getByRole('heading', { name: 'Puzzle activity' }).scrollIntoViewIfNeeded();
		await page
			.getByRole('heading', { name: 'Puzzle activity' })
			.locator('..')
			.screenshot({ path: info.outputPath('training-summary.png') });
		const stats: TrainingStats = await (await page.request.get('/api/v1/training/stats')).json();
		expect(stats.correct_attempts).toBe(initial.correct_attempts + 1);
		expect(stats.incorrect_attempts).toBe(initial.incorrect_attempts + 1);
	} finally {
		await stop();
		rmSync(directory, { recursive: true, force: true });
	}
});
