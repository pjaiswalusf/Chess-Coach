<script lang="ts">
	import { coachingApi } from '#lib/api/coaching.js';
	import { coachingJob } from '#lib/coaching-job.svelte.js';
	import Button from './ui/Button.svelte';

	let {
		game,
		ply,
		profile,
		embedded = false
	}: { game: number; ply: number; profile: string; embedded?: boolean } = $props();
	const job = coachingJob(
		(signal) => coachingApi.get(game, ply, profile, signal),
		(signal) => coachingApi.generate(game, ply, profile, signal)
	);
	const result = $derived(job.result);
</script>

<section
	aria-label="Move coaching"
	class={embedded
		? 'mt-3 space-y-2 border-t border-stone-300 pt-3 text-sm'
		: 'space-y-3 rounded-xl border border-positive-line bg-positive-surface p-5'}
>
	<h3 class={embedded ? 'sr-only' : 'text-lg font-semibold'}>Coaching for ply {ply}</h3>
	{#if job.loading}<p role="status">Loading saved explanation…</p>
	{:else}
		{#if job.error}<p role="alert">Coaching unavailable: {job.error}</p>{/if}
		{#if result?.status === 'done' && result.coach}
			<p class="font-medium">{result.coach.summary}</p>
			{#if 'what_went_wrong' in result.coach}
				{#if embedded}
					<details class="space-y-2">
						<summary class="cursor-pointer font-semibold">Coaching details</summary>
						{@render lesson(result.coach)}
					</details>
				{:else}
					{@render lesson(result.coach)}
				{/if}
			{/if}
			<p class={embedded ? 'text-xs text-stone-600' : 'text-sm text-muted'}>
				Local model explanation · Passed automated checks. Chess prose can still contain errors;
				compare the engine evidence.
			</p>
		{:else if result?.status === 'insufficient_evidence'}
			<p>
				{result.coach?.summary ?? 'The available evidence is insufficient for reliable coaching.'}
			</p>
		{:else if job.active && !job.error}
			<p role="status">Generating… {result?.message ?? 'Waiting for the local coaching worker.'}</p>
		{:else if result?.status === 'failed'}
			<p role="alert">{result.message} ({result.error_code})</p>
		{:else if !job.error && !embedded}<p>No explanation generated yet.</p>{/if}
		{#if result?.status !== 'done' && result?.status !== 'insufficient_evidence'}
			<Button
				primary
				onclick={job.submit}
				disabled={job.active || job.statusError}
				loading={job.submitting}
			>
				{job.submitting ? 'Requesting…' : 'Explain this move'}
			</Button>
		{/if}
		{#if job.statusError}<Button onclick={job.refresh}>Refresh coaching status</Button>{/if}
	{/if}
</section>

{#snippet lesson(coach: {
	what_went_wrong: string;
	why_best_move_works: string;
	lesson: string;
	practice_tip: string;
})}
	<p>{coach.what_went_wrong}</p>
	<p>{coach.why_best_move_works}</p>
	<p><strong>Lesson:</strong> {coach.lesson}</p>
	<p><strong>Practice:</strong> {coach.practice_tip}</p>
{/snippet}
