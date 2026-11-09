import { ApiError, apiErrorMessage } from '#lib/api/errors.js';
import { isActive } from '#lib/api/jobs.js';

export function watchRun<T extends { run_id: number; status: string }>(
	id: () => number | null,
	read: (id: number, signal: AbortSignal) => Promise<T>
) {
	let state = $state<{ data: T | null; error: string; reconnecting: boolean }>({
		data: null,
		error: '',
		reconnecting: false
	});
	let refreshCount = $state(0);

	$effect(() => {
		const run = id();
		void refreshCount;
		state = { data: null, error: '', reconnecting: false };
		if (run === null) return;
		const controller = new AbortController();
		let timer: ReturnType<typeof setTimeout>;
		let delay = 2000;

		async function poll(runId: number) {
			try {
				const data = await read(runId, controller.signal);
				if (controller.signal.aborted || runId !== id()) return;
				state = { data, error: '', reconnecting: false };
				delay = 2000;
				if (isActive(data.status)) timer = setTimeout(() => void poll(runId), delay);
			} catch (error) {
				if (controller.signal.aborted || runId !== id()) return;
				const retry = !(error instanceof ApiError && error.status === 404);
				state.error = apiErrorMessage(error, 'Could not read run status.');
				state.reconnecting = retry;
				if (retry) {
					timer = setTimeout(() => void poll(runId), delay);
					delay = Math.min(delay * 2, 8000);
				}
			}
		}

		void poll(run);
		return () => {
			controller.abort();
			clearTimeout(timer);
		};
	});

	return {
		get state() {
			return state;
		},
		refresh: () => {
			refreshCount++;
		}
	};
}
