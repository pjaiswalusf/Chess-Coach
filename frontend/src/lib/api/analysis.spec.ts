import { afterEach, expect, test, vi } from 'vitest';
import { analysisApi } from './analysis';

afterEach(() => vi.unstubAllGlobals());

test('submits only a historical player selection through the API', async () => {
	const run = { id: 7, status: 'queued', games: [], engine_config_json: {} };
	const fetcher = vi.fn().mockResolvedValue(Response.json(run, { status: 202 }));
	vi.stubGlobal('fetch', fetcher);
	expect(await analysisApi.start(2)).toEqual(run);
	expect(fetcher).toHaveBeenCalledWith(
		'/api/v1/analysis-runs',
		expect.objectContaining({
			method: 'POST',
			body: '{"scope":"pending","tracked_player_id":2}'
		})
	);
});

test('rejects malformed run data before it reaches the analysis view', async () => {
	vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json([{ id: 7, status: 'queued' }])));
	await expect(analysisApi.runs()).rejects.toMatchObject({ kind: 'invalid_response' });
});

test('reports structured retry instructions', async () => {
	vi.stubGlobal(
		'fetch',
		vi
			.fn()
			.mockResolvedValue(
				Response.json({ code: 'WORKER_UNAVAILABLE', message: 'Start the worker.' }, { status: 503 })
			)
	);
	await expect(analysisApi.start(2)).rejects.toThrow('Start the worker.');
});

test('does not resubmit an analysis when the connection drops', async () => {
	const fetcher = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
	vi.stubGlobal('fetch', fetcher);
	await expect(analysisApi.start(2)).rejects.toMatchObject({ kind: 'network' });
	expect(fetcher).toHaveBeenCalledTimes(1);
});
