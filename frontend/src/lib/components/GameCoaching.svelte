<script lang="ts">
	import { coachingApi } from '#lib/api/coaching.js';
	import { coachingJob } from '#lib/coaching-job.svelte.js';
	import Button from './ui/Button.svelte';

	let {
		game,
		profile,
		onSelect
	}: { game: number; profile: string; onSelect: (ply: number) => void } = $props();

	const job = coachingJob(
		(signal) => coachingApi.game(game, profile, signal),
		(signal) => coachingApi.game(game, profile, signal, true),
		true
	);
	const moments = $derived(job.result?.game_review ?? []);
</script>

<section
	aria-label="Game coaching"
	class="space-y-2.5 rounded-2xl bg-stone-50 p-4 text-stone-900 shadow-sm sm:p-5"
>
	<h3 class="text-lg font-bold">Game coaching</h3>
	{#if job.loading}
		<p role="status" class="text-sm text-stone-700">Loading game coaching…</p>
	{:else if job.submitting || (job.active && !job.error)}
		<p role="status" class="text-sm text-stone-700">
			Preparing your game review with the local coach…
		</p>
	{/if}
	{#if job.error || job.result?.status === 'failed'}
		<p role="alert" class="text-sm">
			{job.error || job.result?.message || 'Could not prepare game coaching.'}
		</p>
		<Button onclick={job.statusError ? job.refresh : job.submit}>Retry game coaching</Button>
	{/if}
	{#if moments.length}
		<ol class="space-y-2.5 text-sm">
			{#each moments as moment (moment.ply)}
				<li class="border-t border-stone-200 pt-2.5">
					<button
						type="button"
						onclick={() => onSelect(moment.ply)}
						class="rounded text-left font-bold text-green-800 underline underline-offset-2 hover:text-green-950 focus-visible:outline-2"
						>Review {moment.move}</button
					>
					<p class="mt-1">{moment.played_fact}</p>
					{#if moment.alternative_fact}<p class="mt-1">{moment.alternative_fact}</p>{/if}
					{#if moment.practice_tip}
						<p class="mt-1.5 font-medium">{moment.practice_tip}</p>
					{/if}
				</li>
			{/each}
		</ol>
	{:else if job.result?.status === 'insufficient_evidence'}
		<p class="text-sm text-stone-700">
			This game has too little move evidence for a coaching review.
		</p>
	{/if}
</section>
