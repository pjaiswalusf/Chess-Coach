import { afterEach, expect, test, vi } from 'vitest';
import { apiRequest } from './client.js';
import { ApiError } from './errors.js';

afterEach(() => {
	vi.useRealTimers();
	vi.unstubAllGlobals();
});

test('parses JSON and negotiates JSON without replacing caller headers', async () => {
	const fetcher = vi.fn().mockResolvedValue(Response.json({ status: 'ok' }));
	vi.stubGlobal('fetch', fetcher);
	await expect(apiRequest('/health', { headers: { 'x-test': 'preserved' } })).resolves.toEqual({
		status: 'ok'
	});
	const [, options] = fetcher.mock.calls[0];
	expect(options.headers.get('Accept')).toBe('application/json');
	expect(options.headers.get('X-Test')).toBe('preserved');
	expect(options.redirect).toBe('error');
});

test('retains the HTTP status, code, and safe FastAPI error message', async () => {
	vi.stubGlobal(
		'fetch',
		vi
			.fn()
			.mockResolvedValue(
				Response.json({ code: 'GAME_NOT_FOUND', message: 'Game does not exist.' }, { status: 404 })
			)
	);
	const result = apiRequest('/api/v1/games/42');
	await expect(result).rejects.toBeInstanceOf(ApiError);
	await expect(result).rejects.toMatchObject({
		kind: 'http',
		status: 404,
		code: 'GAME_NOT_FOUND',
		message: 'Game does not exist.'
	});
});

test('classifies a JSON 500 response without showing internal errors', async () => {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue(Response.json({ message: 'Raw traceback' }, { status: 500 }))
	);
	await expect(apiRequest('/api/v1/games')).rejects.toMatchObject({
		kind: 'http',
		status: 500,
		message: 'Request failed (500). Check the backend and retry.'
	});
});

test.each([
	{ body: '<html>Proxy error</html>', status: 502, type: 'text/html' },
	{ body: '{"status":', status: 200, type: 'application/json' }
])('classifies invalid responses ($status $type)', async ({ body, status, type }) => {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue(new Response(body, { status, headers: { 'Content-Type': type } }))
	);
	await expect(apiRequest('/health')).rejects.toMatchObject({ kind: 'invalid_response', status });
});

test('classifies connection failure as a network error', async () => {
	vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
	await expect(apiRequest('/health')).rejects.toMatchObject({ kind: 'network' });
});

test('times out while waiting for response headers', async () => {
	vi.useFakeTimers();
	vi.stubGlobal(
		'fetch',
		vi.fn(
			(_path: string, { signal }: { signal: AbortSignal }) =>
				new Promise((_, reject) => {
					signal.addEventListener('abort', () => reject(signal.reason), { once: true });
				})
		)
	);
	const result = expect(apiRequest('/health', {}, 100)).rejects.toMatchObject({ kind: 'timeout' });
	await vi.advanceTimersByTimeAsync(100);
	await result;
	expect(vi.getTimerCount()).toBe(0);
});

function stallBody() {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (_path: string, { signal }: { signal: AbortSignal }) => {
			const body = new ReadableStream<Uint8Array>({
				start(stream) {
					signal.addEventListener('abort', () => stream.error(signal.reason), { once: true });
				}
			});
			return new Response(body, { headers: { 'Content-Type': 'application/json' } });
		})
	);
}

test('keeps the deadline active until the JSON body arrives', async () => {
	vi.useFakeTimers();
	stallBody();
	const result = expect(apiRequest('/health', {}, 100)).rejects.toMatchObject({ kind: 'timeout' });
	await vi.advanceTimersByTimeAsync(100);
	await result;
	expect(vi.getTimerCount()).toBe(0);
});

test('classifies caller cancellation during a body read', async () => {
	stallBody();
	const controller = new AbortController();
	const result = expect(apiRequest('/health', { signal: controller.signal })).rejects.toMatchObject(
		{
			kind: 'cancelled'
		}
	);
	await Promise.resolve();
	controller.abort();
	await result;
});

test('handles 204 without attempting to read a JSON body', async () => {
	vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
	await expect(apiRequest<void>('/api/v1/games')).resolves.toBeUndefined();
});

test.each(['https://example.com/api/v1/games', '//example.com/health', '/api/v1/%2e%2e/private'])(
	'blocks a path outside the local API before calling fetch (%s)',
	async (path) => {
		const fetcher = vi.fn();
		vi.stubGlobal('fetch', fetcher);
		await expect(apiRequest(path)).rejects.toMatchObject({ kind: 'invalid_response' });
		expect(fetcher).not.toHaveBeenCalled();
	}
);

test('does not send a request if the caller has already cancelled', async () => {
	const fetcher = vi.fn();
	vi.stubGlobal('fetch', fetcher);
	await expect(apiRequest('/health', { signal: AbortSignal.abort() })).rejects.toMatchObject({
		kind: 'cancelled'
	});
	expect(fetcher).not.toHaveBeenCalled();
});
