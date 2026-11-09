import { expect, test } from '@playwright/test';
import type { paths } from '../src/lib/api/generated/schema.js';

test('preserves the shell during a disconnection and reconnects on retry', async ({ page }) => {
	let checks = 0;
	await page.route('**/health', (route) => {
		checks += 1;
		return checks === 1 ? route.abort() : route.fulfill({ json: { status: 'ok' } });
	});
	await page.goto('/');
	await expect(page.getByText('Backend unavailable', { exact: true })).toBeVisible();
	await page.getByRole('navigation').getByRole('link', { name: 'Training' }).click();
	await expect(page.getByRole('heading', { name: 'Training' })).toBeVisible();
	await expect(page.getByText('Backend unavailable', { exact: true })).toBeVisible();
	expect(checks).toBe(1);
	await page.getByRole('button', { name: 'Retry backend connection' }).click();
	await expect(page.getByText('Backend connected', { exact: true })).toBeVisible();
	await expect(page).toHaveURL('/training');
	expect(checks).toBe(2);
});

test('treats an invalid liveness payload as unavailable', async ({ page }) => {
	await page.route('**/health', (route) => route.fulfill({ json: { status: 'healthy' } }));
	await page.goto('/');
	await expect(page.getByText('Backend unavailable', { exact: true })).toBeVisible();
});

type Health =
	paths['/api/v1/system/health']['get']['responses'][200]['content']['application/json'];

const components = {
	database: { status: 'pass', required: true, message: 'Database readable.' },
	stockfish: { status: 'pass', required: false, message: 'Stockfish responds to UCI commands.' },
	ollama: { status: 'pass', required: false, message: 'Ollama is reachable.' },
	ollama_model: { status: 'pass', required: false, message: 'Local model installed.' }
} satisfies Health['components'];

const ready: Health = {
	overall: 'healthy',
	checked_at: '2026-11-09T12:00:00Z',
	components,
	statistics: {
		games_stored: 24,
		games_analyzed: 12,
		pending_games: 12,
		positions_cached: 240,
		active_sync_runs: 0,
		active_analysis_runs: 1,
		active_coaching_jobs: 0
	}
};

const coaching = {
	window_days: 7,
	sample_count: 0,
	latency_p50_ms: null,
	first_schema_failure_rate: null,
	first_schema_sample_count: 0,
	final_failure_rate: null
};

test('shows optional dependency degradation and measured performance while FastAPI remains connected', async ({
	page
}) => {
	await page.route('**/health', (route) => route.fulfill({ json: { status: 'ok' } }));
	await page.route('**/api/v1/system/health', (route) =>
		route.fulfill({
			json: {
				...ready,
				overall: 'degraded',
				components: {
					...components,
					ollama: {
						status: 'warn',
						required: false,
						message: 'Ollama unavailable.',
						action: 'Start Ollama.'
					},
					ollama_model: {
						status: 'skip',
						required: false,
						message: 'Model readiness could not be checked.'
					}
				}
			}
		})
	);
	await page.route('**/api/v1/system/metrics', (route) =>
		route.fulfill({
			json: {
				analysis: {
					run_id: '17',
					positions_per_second: 52.4,
					cache_hit_rate: 76.2,
					duration_ms: 3210,
					games_per_hour: 120
				},
				coaching
			}
		})
	);
	await page.goto('/system');
	await expect(page.getByText('Backend connected', { exact: true })).toBeVisible();
	await expect(page.getByText('Degraded', { exact: true })).toBeVisible();
	const ollama = page.getByText('Ollama', { exact: true }).locator('..');
	await expect(ollama.getByText('Warning', { exact: true })).toBeVisible();
	await expect(ollama.getByText('Start Ollama.')).toBeVisible();
	await expect(page.getByText('New AI explanations are unavailable.')).toBeVisible();
	await expect(page.getByText('24', { exact: true })).toBeVisible();
	await expect(page.getByText('Latest finished analysis run #17')).toBeVisible();
	await expect(page.getByText('52.4 positions/s')).toBeVisible();
	const latency = page.getByText('LLM latency p50').locator('..');
	await expect(latency.getByText('Unavailable', { exact: true })).toBeVisible();
});

test('renders the structured 503 and leaves liveness connected', async ({ page }) => {
	await page.route('**/health', (route) => route.fulfill({ json: { status: 'ok' } }));
	await page.route('**/api/v1/system/health', (route) =>
		route.fulfill({
			status: 503,
			json: {
				...ready,
				overall: 'unavailable',
				components: {
					...components,
					database: {
						status: 'fail',
						required: true,
						message: 'Database unavailable.',
						action: 'Check database access.'
					}
				},
				statistics: null
			}
		})
	);
	await page.route('**/api/v1/system/metrics', (route) =>
		route.fulfill({
			status: 503,
			json: { code: 'DATABASE_UNAVAILABLE', message: 'Check local data access.' }
		})
	);
	await page.goto('/system');
	await expect(page.getByText('Backend connected', { exact: true })).toBeVisible();
	await expect(page.getByText('Check database access.')).toBeVisible();
	await expect(page.getByText('Game counts are unavailable.')).toBeVisible();
	await expect(page.getByText('Games stored', { exact: true })).toHaveCount(0);
	await expect(page.getByText('Metrics unavailable.')).toBeVisible();
});

test('refreshes a healthy system through model degradation and disconnection', async ({ page }) => {
	let offline = false;
	let health = ready;
	await page.route('**/health', (route) =>
		offline ? route.abort() : route.fulfill({ json: { status: 'ok' } })
	);
	await page.route('**/api/v1/system/health', (route) =>
		offline ? route.abort() : route.fulfill({ json: health })
	);
	await page.route('**/api/v1/system/metrics', (route) =>
		offline ? route.abort() : route.fulfill({ json: { analysis: null, coaching } })
	);
	await page.goto('/system');
	await expect(page.getByText('Healthy', { exact: true })).toBeVisible();
	await expect(page.getByText('No finished analysis runs.')).toBeVisible();
	await expect(page.getByText('240', { exact: true })).toBeVisible();
	health = {
		...ready,
		overall: 'degraded',
		components: {
			...components,
			ollama_model: {
				status: 'warn',
				required: false,
				message: 'Model missing.',
				action: 'Pull the configured model.'
			}
		}
	};
	const refresh = page.getByRole('button', { name: 'Refresh status' });
	await refresh.click();
	await expect(page.getByText('Degraded', { exact: true })).toBeVisible();
	await expect(page.getByText('Pull the configured model.')).toBeVisible();
	offline = true;
	await refresh.click();
	await expect(page.getByText('Backend unavailable', { exact: true })).toBeVisible();
	await expect(page.getByText('Backend connected', { exact: true })).toHaveCount(0);
	await expect(page.getByText('240', { exact: true })).toHaveCount(0);
});
