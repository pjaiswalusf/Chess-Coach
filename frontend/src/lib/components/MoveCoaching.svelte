<script lang="ts">
	import { coachingApi, type CoachingResponse } from '#lib/api/coaching.js';
	import type { ReviewRating } from '#lib/api/review.js';
	import { moveRatings } from '#lib/utils/review-rating.js';
	import ReviewRatingIcon from './ReviewRatingIcon.svelte';
	import { coachingJob } from '#lib/coaching-job.svelte.js';
	import Button from './ui/Button.svelte';

	let {
		game,
		ply,
		profile,
		rating
	}: {
		game: number;
		ply: number;
		profile: string;
		rating?: ReviewRating;
	} = $props();
	const job = coachingJob(
		(signal) => coachingApi.get(game, ply, profile, signal),
		(signal) => coachingApi.generate(game, ply, profile, signal)
	);
	const result = $derived(job.result);
</script>

<section
	aria-label="Move coaching"
	class={rating
		? 'space-y-3 rounded-2xl bg-stone-50 p-4 text-sm leading-relaxed text-stone-900 shadow-sm sm:p-5'
		: 'space-y-3 rounded-xl border border-positive-line bg-positive-surface p-5'}
>
	{#if rating}
		{@const mark = moveRatings[rating]}
		<h3
			class={[
				'inline-flex items-center gap-2 rounded-lg bg-stone-900 px-2.5 py-1.5 text-lg font-bold',
				mark.tone
			]}
		>
			<ReviewRatingIcon {rating} />
			{mark.label}
		</h3>
	{:else}
		<h3 class="text-lg font-semibold">Coaching for ply {ply}</h3>
	{/if}
	{#if result?.move_breakdown}
		{@const breakdown = result.move_breakdown}
		{#if rating}
			{#if breakdown.remark}
				<p>{breakdown.remark}</p>
			{:else}
				<p>No remark about this move is available from the backend.</p>
			{/if}
		{:else}
			{@render moveBreakdown(breakdown)}
		{/if}
	{/if}
	{#if job.loading}
		<p role="status">{rating ? 'Loading move commentary…' : 'Loading saved explanation…'}</p>
	{:else if rating}
		{#if job.error && !result?.move_breakdown}
			<p role="alert">Move commentary unavailable: {job.error}</p>
			<Button onclick={job.refresh}>Retry</Button>
		{/if}
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
		{:else if !job.error && !result?.move_breakdown}<p>No explanation generated yet.</p>{/if}
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

{#snippet moveBreakdown(breakdown: NonNullable<CoachingResponse['move_breakdown']>)}
	<div class="space-y-2.5">
		<p class="font-semibold">{breakdown.assessment}</p>
		<dl class="grid gap-2.5">
			<div>
				<dt class="text-xs font-bold uppercase">Played line</dt>
				<dd class="mt-0.5">
					<p class="font-mono text-sm wrap-anywhere">{breakdown.played.san}</p>
					<p class="mt-1">{breakdown.played.key_fact}</p>
				</dd>
			</div>
			{#if breakdown.alternative}
				<div>
					<dt class="text-xs font-bold uppercase">Stockfish’s alternative</dt>
					<dd class="mt-0.5">
						<p class="font-mono text-sm wrap-anywhere">{breakdown.alternative.san}</p>
						<p class="mt-1">{breakdown.alternative.key_fact}</p>
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
