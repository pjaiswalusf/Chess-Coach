<script lang="ts">
	import type { Snippet } from 'svelte';
	import { coachingApi, type CoachingResponse } from '#lib/api/coaching.js';
	import { coachingJob } from '#lib/coaching-job.svelte.js';
	import Button from './ui/Button.svelte';

	let {
		game,
		ply,
		profile,
		evidence,
		evidenceOpen = $bindable(false)
	}: {
		game: number;
		ply: number;
		profile: string;
		evidence?: Snippet;
		evidenceOpen?: boolean;
	} = $props();
	const job = coachingJob(
		(signal) => coachingApi.get(game, ply, profile, signal),
		(signal) => coachingApi.generate(game, ply, profile, signal)
	);
	const result = $derived(job.result);
</script>

<section
	aria-label="Move coaching"
	class={evidence
		? 'space-y-3 rounded-2xl bg-stone-50 p-4 text-sm leading-relaxed text-stone-900 shadow-sm sm:p-5'
		: 'space-y-3 rounded-xl border border-positive-line bg-positive-surface p-5'}
>
	<h3 class={evidence ? 'text-lg font-bold' : 'text-lg font-semibold'}>
		{evidence ? 'Coach’s remarks' : `Coaching for ply ${ply}`}
	</h3>
	{#if result?.move_breakdown}
		{@const breakdown = result.move_breakdown}
		{#if evidence}
			{#if breakdown.remark}
				<p>{breakdown.remark}</p>
			{:else}
				<p>No remark about this move is available from the backend.</p>
			{/if}
			{#if breakdown.alternative || !breakdown.remark}
				<p>
					<strong class="block">Possible continuation after this move</strong>
					{breakdown.played.key_fact}
				</p>
			{/if}
			{#if breakdown.alternative}
				<p>
					<strong class="block">Stockfish’s alternative</strong>
					{breakdown.alternative.key_fact}
				</p>
			{:else if !breakdown.remark}
				<p class="text-muted">Stockfish also chose this move.</p>
			{/if}
		{:else}
			{@render moveBreakdown(breakdown, true)}
		{/if}
	{/if}
	{#if job.loading}<p role="status">Loading saved explanation…</p>
	{:else}
		{#if job.error}<p role="alert">Coaching unavailable: {job.error}</p>{/if}
		{#if result?.status === 'done' && result.coach}
			{#if 'what_went_wrong' in result.coach}
				{#if result.move_breakdown}
					<details class="space-y-2">
						<summary class="cursor-pointer font-semibold">Practice this position</summary>
						<p>{result.coach.lesson}</p>
						<p>{result.coach.practice_tip}</p>
					</details>
				{:else}
					<p class="font-medium">{result.coach.summary}</p>
					{@render lesson(result.coach)}
				{/if}
			{/if}
		{:else if result?.status === 'insufficient_evidence'}
			{#if !result.move_breakdown}
				<p>
					{result.coach?.summary ??
						'The available evidence is insufficient for additional coaching.'}
				</p>
			{/if}
		{:else if job.active && !job.error}
			<p role="status">Generating… {result?.message ?? 'Waiting for the local coaching worker.'}</p>
		{:else if result?.status === 'failed'}
			<p role="alert">{result.message} ({result.error_code})</p>
		{:else if !job.error && !evidence && !result?.move_breakdown}<p>
				No explanation generated yet.
			</p>{/if}
		{#if result?.status !== 'done' && result?.status !== 'insufficient_evidence'}
			<Button
				primary
				onclick={job.submit}
				disabled={job.active || job.statusError}
				loading={job.submitting}
			>
				{job.submitting ? 'Requesting…' : evidence ? 'Get a practice tip' : 'Explain this move'}
			</Button>
		{/if}
		{#if job.statusError}<Button onclick={job.refresh}>Refresh coaching status</Button>{/if}
	{/if}
	{#if evidence}
		<details bind:open={evidenceOpen} class="space-y-2 rounded-lg border border-line px-3 py-2">
			<summary class="cursor-pointer text-sm font-semibold">Move evidence</summary>
			{@render evidence()}
			{#if result?.move_breakdown}{@render moveBreakdown(result.move_breakdown, false)}{/if}
		</details>
	{/if}
</section>

{#snippet moveBreakdown(
	breakdown: NonNullable<CoachingResponse['move_breakdown']>,
	showFacts: boolean
)}
	<div class="space-y-2.5">
		<p class="font-semibold">{breakdown.assessment}</p>
		<dl class="grid gap-2.5">
			<div>
				<dt class="text-xs font-bold uppercase">Played line</dt>
				<dd class="mt-0.5">
					<p class="font-mono text-sm wrap-anywhere">{breakdown.played.san}</p>
					{#if showFacts}<p class="mt-1">{breakdown.played.key_fact}</p>{/if}
				</dd>
			</div>
			{#if breakdown.alternative}
				<div>
					<dt class="text-xs font-bold uppercase">Stockfish’s alternative</dt>
					<dd class="mt-0.5">
						<p class="font-mono text-sm wrap-anywhere">{breakdown.alternative.san}</p>
						{#if showFacts}<p class="mt-1">{breakdown.alternative.key_fact}</p>{/if}
					</dd>
				</div>
			{/if}
		</dl>
	</div>
{/snippet}

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
