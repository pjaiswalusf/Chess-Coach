import { defineConfig } from '@playwright/test';

const live = process.env.PHASE16_LIVE === '1';
const baseURL = live ? 'http://127.0.0.1:5173' : 'http://127.0.0.1:4173';

export default defineConfig({
	use: { baseURL },
	webServer: {
		command: live
			? 'pnpm dev --strictPort'
			: 'pnpm build && pnpm preview --host 127.0.0.1 --port 4173 --strictPort',
		url: baseURL
	},
	testMatch: ['**/*.e2e.{ts,js}', '**/e2e/*.spec.ts']
});
