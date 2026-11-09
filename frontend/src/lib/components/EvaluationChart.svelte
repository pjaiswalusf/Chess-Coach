<script lang="ts">
	import type { ReviewMove } from '#lib/api/review.js';

	let { moves }: { moves: ReviewMove[] } = $props();
	const points = $derived([
		moves[0]?.eval_before_cp_white ?? null,
		...moves.map((m) => m.eval_after_cp_white)
	]);
	const max = $derived(
		points.reduce<number>(
			(largest, cp) => (cp === null ? largest : Math.max(largest, Math.abs(cp))),
			1
		)
	);
	const xy = $derived(
		points.map((cp, i) =>
			cp === null
				? null
				: {
						x: 12 + (376 * i) / Math.max(1, points.length - 1),
						y: 50 - (40 * cp) / max,
						cp,
						ply: i
					}
		)
	);
	const line = $derived(
		xy
			.map((point, index) => (point ? `${xy[index - 1] ? 'L' : 'M'}${point.x} ${point.y}` : ''))
			.join(' ')
	);
</script>

<section aria-label="Evaluation progression" class="space-y-2">
	<h3 class="text-lg font-semibold">Evaluation progression</h3>
	{#if xy.some((point) => point !== null)}
		<p class="text-sm text-slate-700">
			White perspective (centipawns). Above the line favors White. Gaps mark mate or missing scores.
		</p>
		<svg
			viewBox="0 0 400 100"
			role="img"
			aria-label="Stockfish evaluations from the initial position to the final ply"
			class="w-full rounded-lg bg-slate-100"
		>
			<line x1="12" x2="388" y1="50" y2="50" class="stroke-slate-500" stroke-dasharray="4 3" />
			<path d={line} fill="none" class="stroke-emerald-800" stroke-width="2" />
			{#each xy as point, index (index)}
				{#if point}
					<circle cx={point.x} cy={point.y} r="2.5" class="fill-emerald-800">
						<title
							>{point.ply ? `After ply ${point.ply}` : 'Initial position'}: {point.cp} cp (White)</title
						>
					</circle>
				{/if}
			{/each}
		</svg>
	{:else}
		<p>No centipawn scores are available to plot.</p>
	{/if}
</section>
