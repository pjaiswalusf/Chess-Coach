import { ApiError, apiErrorMessage } from '#lib/api/errors.js';
import { isActive } from '#lib/api/jobs.js';

const pollingIntervalMs = 2_000;
const maxReconnectIntervalMs = 8_000;

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
		let delayMs = pollingIntervalMs;

		async function poll(runId: number) {
			try {
				const data = await read(runId, controller.signal);
				if (controller.signal.aborted || runId !== id()) return;
				state = { data, error: '', reconnecting: false };
				delayMs = pollingIntervalMs;
				if (isActive(data.status)) timer = setTimeout(() => void poll(runId), delayMs);
			} catch (error) {
				if (controller.signal.aborted || runId !== id()) return;
				const canRetry = !(error instanceof ApiError && error.status === 404);
				state.error = apiErrorMessage(error, 'Could not read run status.');
				state.reconnecting = canRetry;
				if (!canRetry) return;
				timer = setTimeout(() => void poll(runId), delayMs);
				delayMs = Math.min(delayMs * 2, maxReconnectIntervalMs);
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
