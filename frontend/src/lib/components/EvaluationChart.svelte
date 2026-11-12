<script lang="ts">
	import type { ReviewMove } from '#lib/api/review.js';
	import { evaluationLabel, type PositionScore } from '#lib/utils/display.js';
	import { moveRatings } from '#lib/utils/review-rating.js';

	const swingThresholdCp = 80;

	let {
		moves = [],
		variationMoves,
		scores,
		position,
		onSelect
	}: {
		moves?: ReviewMove[];
		variationMoves?: string[];
		scores: PositionScore[];
		position: number;
		onSelect: (ply: number) => void;
	} = $props();
	const length = $derived(variationMoves?.length ?? moves.length);
	const scale = $derived(Math.max(100, ...scores.map(({ cp }) => Math.abs(cp ?? 0))));
	const x = (ply: number) => 5 + (390 * ply) / Math.max(1, length);
	const points = $derived(
		scores.map(({ cp, mate, whiteWins }, ply) => {
			if (variationMoves && mate !== null) return { x: x(ply), y: whiteWins ? 7 : 101 };
			return cp === null ? null : { x: x(ply), y: 54 - (45 * cp) / scale };
		})
	);
	const line = $derived(
		points
			.map((point, ply) => (point ? `${points[ply - 1] ? 'L' : 'M'}${point.x} ${point.y}` : ''))
			.join(' ')
	);
	const area = $derived(
		points
			.map((point, ply) => {
				if (!point) return '';
				const start = points[ply - 1] ? '' : `M${point.x} 108`;
				const end = points[ply + 1] ? '' : `L${point.x} 108Z`;
				return `${start}L${point.x} ${point.y}${end}`;
			})
			.join(' ')
	);
	const swingMarks = $derived(
		moves.map((move) => {
			const before = move.eval_before_cp_white;
			const after = move.eval_after_cp_white;
			const beforeMate = move.mate_before_winner;
			const afterMate = move.mate_after_winner;
			const significant =
				before !== null && after !== null
					? Math.abs(after - before) >= swingThresholdCp
					: (before !== null || beforeMate !== null) &&
						(after !== null || afterMate !== null) &&
						beforeMate !== afterMate;
			return significant ? moveRatings[move.rating] : null;
		})
	);
	const current = $derived(scores[position]);
	const scoreLabel = $derived(
		current ? evaluationLabel(current.cp, current.mate, current.whiteWins) : 'Unavailable'
	);
	const positionLabel = $derived(
		variationMoves
			? position === 0
				? 'Branch point'
				: `After ${variationMoves[position - 1]}`
			: position === 0
				? 'Starting position'
				: `After ply ${position}, ${moves[position - 1].played_move_san} · ${moveRatings[moves[position - 1].rating].label}`
	);
</script>

<section
	aria-label={variationMoves ? 'Variation evaluation' : 'Evaluation progression'}
	class="space-y-2"
>
	<div class="flex flex-wrap items-center justify-between gap-x-2">
		<h3 class="text-sm font-semibold">
			{variationMoves ? 'Variation evaluation' : 'Evaluation progression'}
		</h3>
		{#if scores.length}
			<span
				class="rounded bg-square-light px-2 py-0.5 text-xs font-bold text-square-ink tabular-nums"
			>
				{scoreLabel}
			</span>
		{/if}
	</div>
	{#if scores.some(({ cp, mate }) => cp !== null || mate !== null)}
		<div
			class="relative overflow-hidden rounded-lg border border-line bg-raised focus-within:ring-2 focus-within:ring-accent"
		>
			<svg
				viewBox="0 0 400 108"
				preserveAspectRatio="none"
				role="img"
				aria-label={variationMoves
					? 'Stockfish evaluations along this variation'
					: 'Stockfish evaluations from the initial position to the final ply'}
				class="h-27 w-full"
			>
				<path d={area} class="fill-neutral-100" />
				<line x1="0" x2="400" y1="54" y2="54" class="stroke-neutral-500" stroke-dasharray="4 3" />
				<path
					d={line}
					fill="none"
					class="stroke-white"
					stroke-width="1.5"
					vector-effect="non-scaling-stroke"
				/>
				<line
					x1={x(position)}
					x2={x(position)}
					y1="0"
					y2="108"
					class={['stroke-current', swingMarks[position - 1]?.tone ?? 'text-stone-300']}
					stroke-width="2"
					vector-effect="non-scaling-stroke"
				/>
				{#each scores as score, ply (ply)}
					{@const move = moves[ply - 1]}
					{@const mark = swingMarks[ply - 1]}
					{@const y = score.mate !== null ? (score.whiteWins ? 7 : 101) : points[ply]?.y}
					{#if y !== undefined && (variationMoves || mark || position === ply)}
						<circle
							data-ply={ply}
							cx={x(ply)}
							cy={y}
							r={position === ply ? 4.5 : 2.75}
							class={['fill-current stroke-neutral-900', mark?.tone ?? 'text-stone-300']}
							stroke-width="0.8"
							vector-effect="non-scaling-stroke"
						>
							<title
								>{variationMoves
									? (variationMoves[ply - 1] ?? 'Branch point')
									: move
										? `${move.played_move_san} · ${moveRatings[move.rating].label}`
										: 'Starting position'}</title
							>
						</circle>
					{/if}
				{/each}
			</svg>
			<input
				type="range"
				min="0"
				max={length}
				value={position}
				aria-label={variationMoves
					? 'Jump to variation position on evaluation graph'
					: 'Jump to position on evaluation graph'}
				aria-valuetext={`${positionLabel} · ${scoreLabel} (White perspective)`}
				oninput={(event) => onSelect(event.currentTarget.valueAsNumber)}
				class="absolute inset-0 m-0 size-full cursor-pointer opacity-0"
			/>
		</div>
		<p class="text-xs text-muted">
			Above center favors White.
			{#if !variationMoves}
				Colored dots mark swings of {swingThresholdCp / 100} pawns or more, or a forced mate gained or
				lost.
			{/if}
		</p>
	{:else}
		<p class="text-sm text-muted">
			{variationMoves
				? 'Scores appear as Stockfish evaluates the line.'
				: 'No stored scores are available to plot.'}
		</p>
	{/if}
</section>
