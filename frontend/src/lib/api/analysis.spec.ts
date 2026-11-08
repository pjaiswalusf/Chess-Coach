import { afterEach, expect, test, vi } from 'vitest';
import { analysisApi } from './analysis';

afterEach(() => vi.unstubAllGlobals());

test('submits only a historical player selection through the API', async () => {
	const fetcher = vi
		.fn()
		.mockResolvedValue(new Response(JSON.stringify({ id: 7 }), { status: 202 }));
	vi.stubGlobal('fetch', fetcher);
	expect(await analysisApi.start(2)).toEqual({ id: 7 });
	expect(fetcher).toHaveBeenCalledWith(
		'/api/v1/analysis-runs',
		expect.objectContaining({ method: 'POST', body: '{"tracked_player_id":2}' })
	);
});

test('reports structured retry instructions', async () => {
	vi.stubGlobal(
		'fetch',
		vi
			.fn()
			.mockResolvedValue(
				new Response(JSON.stringify({ detail: { message: 'Start the worker.' } }), { status: 503 })
			)
	);
	await expect(analysisApi.start(2)).rejects.toThrow('Start the worker.');
});

test('handles an unavailable development proxy', async () => {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue(new Response('<html>Unavailable</html>', { status: 502 }))
	);
	await expect(analysisApi.runs()).rejects.toThrow('Request failed (502)');
});
