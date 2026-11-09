import { defineConfig } from '@playwright/test';

const live = process.env.PHASE16_LIVE === '1';
const offline =
	!process.env.PHASE16_LIVE && process.env.PHASE10_REAL !== '1' && !process.env.PHASE18_TRAINING_DB;
const baseURL = live ? 'http://127.0.0.1:5173' : 'http://127.0.0.1:4173';

export default defineConfig({
	use: { baseURL, screenshot: 'only-on-failure', trace: 'retain-on-failure' },
	webServer: {
		command: live
			? 'pnpm dev --strictPort'
			: 'pnpm build && pnpm preview --host 127.0.0.1 --port 4173 --strictPort',
		url: baseURL,
		env: { CHESS_COACH_E2E: offline ? '1' : '0' },
		reuseExistingServer: false,
		timeout: 120_000
	},
	testMatch: ['**/*.e2e.{ts,js}', '**/e2e/*.spec.ts'],
	testIgnore: offline ? [] : ['**/e2e/complete-workflow.spec.ts']
});
