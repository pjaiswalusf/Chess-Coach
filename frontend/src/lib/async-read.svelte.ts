import { untrack } from 'svelte';
import { apiErrorMessage } from '#lib/api/errors.js';

type ReadState<T> =
	| { status: 'loading' }
	| { status: 'success'; data: T }
	| { status: 'empty' }
	| { status: 'error'; message: string };

export function asyncRead<T>(
	read: (signal: AbortSignal) => Promise<T>,
	fallback: string,
	isEmpty?: (data: T) => boolean,
	key?: () => unknown
) {
	let state = $state<ReadState<T>>({ status: 'loading' });
	let active: AbortController | undefined;

	async function refresh() {
		active?.abort();
		const request = new AbortController();
		active = request;
		state = { status: 'loading' };
		try {
			const data = await read(request.signal);
			if (!request.signal.aborted)
				state = isEmpty?.(data) ? { status: 'empty' } : { status: 'success', data };
		} catch (error) {
			if (!request.signal.aborted)
				state = { status: 'error', message: apiErrorMessage(error, fallback) };
		} finally {
			if (active === request) active = undefined;
		}
	}

	$effect(() => {
		key?.();
		untrack(() => void refresh());
		return () => active?.abort();
	});

	return {
		get state() {
			return state;
		},
		refresh
	};
}
