import { ApiError } from './errors.js';

export function isRecord(value: unknown): value is Record<string, unknown> {
	return value !== null && typeof value === 'object' && !Array.isArray(value);
}

export function invalidResponse(status?: number): ApiError {
	return new ApiError('invalid_response', 'The backend returned an unexpected response.', status);
}

export async function apiRequest<T>(
	path: string,
	init: RequestInit = {},
	timeoutMs = 8000
): Promise<T> {
	const pathname = path.split(/[?#]/, 1)[0];
	if (
		(pathname !== '/health' && !pathname.startsWith('/api/v1/')) ||
		new URL(path, 'https://local-api.invalid').pathname !== pathname
	) {
		throw new ApiError('invalid_response', 'Invalid local API path.');
	}

	const controller = new AbortController();
	const cancelled = new ApiError('cancelled', 'Request was cancelled.');
	const cancel = () => controller.abort(cancelled);
	const headers = new Headers(init.headers);
	headers.set('Accept', 'application/json');

	if (init.signal?.aborted) throw cancelled;
	init.signal?.addEventListener('abort', cancel, { once: true });
	const timer = setTimeout(() => {
		controller.abort(new ApiError('timeout', 'The request timed out. Please retry.'));
	}, timeoutMs);

	try {
		const response = await fetch(path, {
			...init,
			headers,
			redirect: 'error',
			signal: controller.signal
		});
		controller.signal.throwIfAborted();
		if (response.status === 204) return undefined as T;

		const mediaType = response.headers.get('content-type')?.split(';', 1)[0].trim().toLowerCase();
		if (mediaType !== 'application/json' && !mediaType?.endsWith('+json')) {
			throw invalidResponse(response.status);
		}

		const body = await response.text();
		controller.signal.throwIfAborted();
		let payload: unknown;
		try {
			payload = JSON.parse(body);
		} catch {
			throw new ApiError('invalid_response', 'The backend returned invalid JSON.', response.status);
		}

		if (!response.ok) {
			const error = isRecord(payload) ? payload : {};
			const code = typeof error.code === 'string' ? error.code : undefined;
			const safeStatus = response.status < 500 || response.status === 503;
			const message =
				safeStatus && typeof error.message === 'string' && error.message.trim()
					? error.message
					: 'Request failed (' + response.status + '). Check the backend and retry.';
			throw new ApiError('http', message, response.status, code);
		}

		return payload as T;
	} catch (error) {
		controller.signal.throwIfAborted();
		if (error instanceof ApiError) throw error;
		throw new ApiError('network', 'Cannot reach the local backend. Check that FastAPI is running.');
	} finally {
		clearTimeout(timer);
		init.signal?.removeEventListener('abort', cancel);
	}
}
