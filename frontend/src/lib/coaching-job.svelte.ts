import { onMount } from 'svelte';
import { coachingApi, type CoachingResponse } from '#lib/api/coaching.js';
import { apiErrorMessage } from '#lib/api/errors.js';

export function coachingJob(
	read: (signal: AbortSignal) => Promise<CoachingResponse>,
	generate: (signal: AbortSignal) => Promise<CoachingResponse>,
	auto = false
) {
	let result = $state<CoachingResponse | null>(null);
	let loading = $state(true);
	let submitting = $state(false);
	let error = $state('');
	let statusError = $state(false);
	const active = $derived(result?.status === 'queued' || result?.status === 'running');
	const lifetime = new AbortController();
	let polls = 0;
	let timer: ReturnType<typeof setTimeout>;

	function accept(value: CoachingResponse) {
		if (lifetime.signal.aborted) return;
		result = value;
		error = '';
		statusError = false;
		if ((value.status === 'queued' || value.status === 'running') && value.job_id) {
			const id = value.job_id;
			timer = setTimeout(() => void poll(id), 1500);
		}
	}

	async function poll(id: number) {
		if (++polls > 120) {
			error = 'Coaching is still pending. Check the local worker, then refresh status.';
			statusError = true;
			return;
		}
		try {
			accept(await coachingApi.job(id, lifetime.signal));
		} catch (cause) {
			if (lifetime.signal.aborted) return;
			error = apiErrorMessage(cause, 'Could not read coaching status.');
			statusError = true;
		}
	}

	async function refresh() {
		clearTimeout(timer);
		polls = 0;
		loading = true;
		try {
			accept(await read(lifetime.signal));
		} catch (cause) {
			if (lifetime.signal.aborted) return;
			error = apiErrorMessage(cause, 'Could not load saved coaching.');
			statusError = true;
		} finally {
			if (!lifetime.signal.aborted) loading = false;
		}
		if (auto && result?.status === 'not_generated') await submit();
	}

	async function submit() {
		if (lifetime.signal.aborted || submitting || active || loading || statusError) return;
		submitting = true;
		polls = 0;
		try {
			accept(await generate(lifetime.signal));
		} catch (cause) {
			if (!lifetime.signal.aborted)
				error = apiErrorMessage(cause, 'Coaching unavailable. Check Ollama and retry.');
		} finally {
			if (!lifetime.signal.aborted) submitting = false;
		}
	}

	onMount(() => {
		void refresh();
		return () => {
			lifetime.abort();
			clearTimeout(timer);
		};
	});

	return {
		get result() {
			return result;
		},
		get loading() {
			return loading;
		},
		get submitting() {
			return submitting;
		},
		get active() {
			return active;
		},
		get statusError() {
			return statusError;
		},
		get error() {
			return error;
		},
		refresh,
		submit
	};
}
