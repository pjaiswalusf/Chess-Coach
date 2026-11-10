import { defineConfig } from 'vitest/config';
import { playwright } from '@vitest/browser-playwright';
import tailwindcss from '@tailwindcss/vite';
import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';

const backend = {
	target: `http://127.0.0.1:${process.env.CHESS_COACH_E2E === '1' ? 8001 : 8000}`,
	changeOrigin: false
};
const proxy = { '/api/': backend, '^/health(?:/(?:live|ready))?(?:$|\\?)': backend };
const loopback = { host: '127.0.0.1', strictPort: true, cors: false, proxy };

export default defineConfig({
	plugins: [
		tailwindcss(),

		sveltekit({
			compilerOptions: {
				// Force runes mode for the project, except for libraries.
				// Can be removed in Svelte 6.
				runes: ({ filename }) =>
					filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			},

			adapter: adapter({ fallback: 'index.html' })
		})
	],

	// Both local modes use the same same-origin FastAPI transport.
	server: { ...loopback, port: 5173 },
	preview: { ...loopback, port: 4173 },

	test: {
		expect: {
			requireAssertions: true
		},

		projects: [
			{
				extends: './vite.config.ts',
				test: {
					name: 'client',

					browser: {
						enabled: true,
						provider: playwright(),
						instances: [
							{
								browser: 'chromium',
								headless: true
							}
						]
					},

					include: ['src/**/*.svelte.{test,spec}.{js,ts}'],
					exclude: ['src/lib/server/**']
				}
			},

			{
				extends: './vite.config.ts',

				test: {
					name: 'server',
					environment: 'node',
					include: ['src/**/*.{test,spec}.{js,ts}'],
					exclude: ['src/**/*.svelte.{test,spec}.{js,ts}']
				}
			}
		]
	}
});
