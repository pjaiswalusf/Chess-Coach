<script lang="ts">
	import { onMount } from 'svelte';
	import { coachingApi, type CoachingResponse } from '#lib/api/coaching.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import Button from './ui/Button.svelte';

	let { game, ply, profile }: { game: number; ply: number; profile: string } = $props();
	let result = $state<CoachingResponse | null>(null);
	let loading = $state(true);
	let submitting = $state(false);
	let error = $state('');
	const lifetime = new AbortController();
	let polls = 0;
	let timer: ReturnType<typeof setTimeout>;
	const active = $derived(result?.status === 'queued' || result?.status === 'running');

	function accept(value: CoachingResponse) {
		if (lifetime.signal.aborted) return;
		result = value;
		error = '';
		if ((value.status === 'queued' || value.status === 'running') && value.job_id) {
			clearTimeout(timer);
			timer = setTimeout(() => void poll(value.job_id!), 1500);
		}
	}

	async function poll(id: number) {
		if (++polls > 120) {
			error = 'Coaching is still pending. Check the local worker, then refresh status.';
			polls = 0;
			return;
		}
		try {
			accept(await coachingApi.job(id, lifetime.signal));
		} catch (cause) {
			if (!lifetime.signal.aborted)
				error = apiErrorMessage(cause, 'Could not read coaching status.');
		}
	}

	onMount(() => {
		void coachingApi
			.get(game, ply, profile, lifetime.signal)
			.then(accept)
			.catch((cause: unknown) => {
				if (!lifetime.signal.aborted) error = apiErrorMessage(cause, 'Could not load coaching.');
			})
			.finally(() => {
				if (!lifetime.signal.aborted) loading = false;
			});
		return () => {
			lifetime.abort();
			clearTimeout(timer);
		};
	});

	async function generate() {
		if (submitting || active) return;
		submitting = true;
		try {
			accept(await coachingApi.generate(game, ply, profile, lifetime.signal));
		} catch (cause) {
			if (!lifetime.signal.aborted)
				error = apiErrorMessage(cause, 'Coaching unavailable. Check Ollama and retry.');
		} finally {
			if (!lifetime.signal.aborted) submitting = false;
		}
	}
</script>

<section
	aria-label="Move coaching"
	class="space-y-3 rounded-xl border border-emerald-200 bg-emerald-50 p-5"
>
	<h3 class="text-lg font-semibold">Coaching for ply {ply}</h3>
	{#if loading}<p role="status">Loading saved explanation…</p>
	{:else}
		{#if error}<p role="alert">{error}</p>{/if}
		{#if result?.status === 'done' && result.coach}
			<p class="font-medium">{result.coach.summary}</p>
			{#if 'what_went_wrong' in result.coach}
				<p>{result.coach.what_went_wrong}</p>
				<p>{result.coach.why_best_move_works}</p>
				<p><strong>Lesson:</strong> {result.coach.lesson}</p>
				<p><strong>Practice:</strong> {result.coach.practice_tip}</p>
			{/if}
			<p class="text-sm text-slate-600">
				Local model explanation · Passed automated checks. Chess prose can still contain errors;
				compare the engine evidence above.
			</p>
		{:else if result?.status === 'insufficient_evidence'}
			<p>
				{result.coach?.summary ?? 'The available evidence is insufficient for reliable coaching.'}
			</p>
		{:else if active && !error}
			<p role="status">Generating… {result?.message ?? 'Waiting for the local coaching worker.'}</p>
		{:else if result?.status === 'failed'}
			<p role="alert">{result.message} ({result.error_code})</p>
		{:else if !error}<p>No explanation generated yet.</p>{/if}
		{#if result?.status !== 'done' && result?.status !== 'insufficient_evidence'}
			<Button onclick={generate} disabled={active} loading={submitting}>
				{submitting ? 'Requesting…' : 'Explain this move'}
			</Button>
		{/if}
		{#if error && active && result?.job_id}
			<button onclick={() => poll(result!.job_id!)} class="text-emerald-800 underline"
				>Refresh coaching status</button
			>
		{/if}
	{/if}
</section>
