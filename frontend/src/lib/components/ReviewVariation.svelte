<script lang="ts">
	import type { VariationEvaluation } from '#lib/api/review.js';
	import type { PositionScore } from '#lib/utils/display.js';
	import EvaluationChart from './EvaluationChart.svelte';
	import type { reviewVariation } from './review-variation.svelte.js';
	import Button from './ui/Button.svelte';
	import ErrorMessage from './ui/ErrorMessage.svelte';

	let {
		variation,
		rootScore,
		rootBest,
		rootContinuation
	}: {
		variation: ReturnType<typeof reviewVariation>;
		rootScore: PositionScore | undefined;
		rootBest: string | null;
		rootContinuation: string;
	} = $props();

	const emptyScore: PositionScore = { cp: null, mate: null, whiteWins: null };
	const current = $derived(variation.current);
	const evaluation = $derived(current?.evaluation);
	const bestMove = $derived(variation.cursor === 0 ? rootBest : evaluation?.best_move);
	const continuation = $derived(
		variation.cursor === 0 ? rootContinuation : evaluation?.continuation
	);
	const names = $derived(variation.nodes.map((node) => node?.san ?? ''));
	const scores = $derived([
		rootScore ?? emptyScore,
		...variation.nodes.map((node) => toScore(node?.evaluation))
	]);

	function toScore(value: VariationEvaluation | null | undefined): PositionScore {
		return value ? { cp: value.cp, mate: value.mate, whiteWins: value.white_wins } : emptyScore;
	}
</script>

<section aria-label="Variation analysis" class="space-y-3 rounded-lg border border-line p-3">
	<h3 class="text-sm font-semibold">Variation</h3>
	<p role="status" class="text-sm text-muted">
		{#if variation.moving}Playing move…
		{:else if !current}Branch point
		{:else if current.outcome}Variation ended · {current.outcome}
		{:else if variation.atLimit}Variation limit reached.
		{:else}{current.side_to_move === 'white' ? 'White' : 'Black'} to move.{/if}
	</p>
	<div role="group" aria-label="Variation moves" class="flex flex-wrap gap-1">
		{#each ['Branch point', ...names] as name, index (index)}
			<button
				type="button"
				disabled={variation.moving}
				aria-current={variation.cursor === index ? 'step' : undefined}
				class={[
					'rounded-md px-2 py-1 text-sm focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50',
					variation.cursor === index
						? 'bg-positive-surface text-accent'
						: 'bg-raised text-ink hover:bg-panel'
				]}
				onclick={() => variation.jump(index)}>{name}</button
			>
		{/each}
	</div>

	{#if current?.error}
		<ErrorMessage
			title="Evaluation unavailable."
			message={current.error}
			retry={variation.retryEvaluation}
		/>
	{:else if current && !evaluation}
		<p role="status" class="text-sm text-muted">Stockfish is evaluating this position…</p>
	{:else if bestMove && continuation}
		<section aria-label="Variation engine line" class="space-y-2 rounded-lg bg-panel p-3">
			<h4 class="text-sm font-semibold">Engine best line</h4>
			<p class="font-mono text-sm wrap-anywhere">{continuation}</p>
			<Button
				disabled={variation.moving ||
					!!variation.promotions.length ||
					!variation.legal.includes(bestMove)}
				onclick={() => bestMove && variation.play(bestMove)}>Play best move</Button
			>
		</section>
	{/if}
	<EvaluationChart
		variationMoves={names}
		{scores}
		position={variation.cursor}
		onSelect={variation.jump}
	/>
</section>
