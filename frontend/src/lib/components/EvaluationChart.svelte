<script lang="ts">
	import type { ReviewMove } from '#lib/api/review.js';
	import { evaluationLabel, type PositionScore } from '#lib/utils/display.js';
	import { moveRatings } from '#lib/utils/review-rating.js';

	const swingThresholdCp = 200;
	const maxSwingMarks = 6;
	const plotWidth = 400;
	const plotHeight = 108;
	const markerInset = 5;
	const traceClip = $props.id();

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
	const x = (ply: number) => (plotWidth * ply) / Math.max(1, length);
	const markerX = (value: number) =>
		Math.max(markerInset, Math.min(plotWidth - markerInset, value));
	const points = $derived(
		scores.map(({ cp, mate, whiteWins }, ply) => {
			if (mate !== null && whiteWins !== null) return { x: x(ply), y: whiteWins ? 0 : plotHeight };
			// Use the same display scale in every game and reserve the edges for mate.
			return cp === null ? null : { x: x(ply), y: 54 - 45 * Math.tanh(cp / 500) };
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
				const start = points[ply - 1] ? '' : `M${point.x} ${plotHeight}`;
				const end = points[ply + 1] ? '' : `L${point.x} ${plotHeight}Z`;
				return `${start}L${point.x} ${point.y}${end}`;
			})
			.join(' ')
	);
	const swingMarks = $derived.by(() => {
		const candidates = moves.flatMap((move, index) => {
			const before = scores[index];
			const after = scores[index + 1];
			const from = points[index];
			const to = points[index + 1];
			if (!from || !to) return [];
			const significant =
				before.cp !== null && after.cp !== null
					? Math.abs(after.cp - before.cp) >= swingThresholdCp
					: before.whiteWins !== after.whiteWins;
			return significant
				? [{ ply: index + 1, distance: Math.abs(to.y - from.y), mark: moveRatings[move.rating] }]
				: [];
		});
		return new Map(
			candidates
				.sort((left, right) => right.distance - left.distance)
				.slice(0, maxSwingMarks)
				.map(({ ply, mark }) => [ply, mark])
		);
	});
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
	{#if points.some((point) => point !== null)}
		<div
			class="relative overflow-hidden rounded-lg border border-line bg-raised focus-within:ring-2 focus-within:ring-accent"
		>
			<svg
				viewBox={`0 0 ${plotWidth} ${plotHeight}`}
				preserveAspectRatio="none"
				role="img"
				aria-label={variationMoves
					? 'Stockfish evaluations along this variation'
					: 'Stockfish evaluations from the initial position to the final ply'}
				class="h-27 w-full"
			>
				<defs>
					<clipPath id={traceClip}>
						<!-- Keep the white trace from painting a strip at the bottom during Black mate. -->
						<rect width={plotWidth} height={plotHeight - 1} />
					</clipPath>
				</defs>
				<path d={area} data-series="evaluation-fill" class="fill-neutral-100" />
				<line
					x1="0"
					x2={plotWidth}
					y1="54"
					y2="54"
					class="stroke-neutral-500"
					stroke-dasharray="4 3"
				/>
				<path
					d={line}
					data-series="evaluation"
					fill="none"
					class="stroke-white"
					clip-path={`url(#${traceClip})`}
					stroke-width="1.5"
					vector-effect="non-scaling-stroke"
				/>
				<line
					x1={markerX(x(position))}
					x2={markerX(x(position))}
					y1="0"
					y2={plotHeight}
					class={['stroke-current', swingMarks.get(position)?.tone ?? 'text-stone-300']}
					stroke-width="2"
					vector-effect="non-scaling-stroke"
				/>
				{#each points as point, ply (ply)}
					{@const move = moves[ply - 1]}
					{@const mark = swingMarks.get(ply)}
					{@const isolated = !points[ply - 1] && !points[ply + 1]}
					{#if point && (variationMoves || mark || position === ply || isolated)}
						<circle
							data-ply={ply}
							data-swing={mark ? '' : undefined}
							cx={markerX(point.x)}
							cy={Math.max(markerInset, Math.min(plotHeight - markerInset, point.y))}
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
				Up to {maxSwingMarks} colored dots mark the largest swings of at least {swingThresholdCp /
					100}
				pawns or a change in forced mate.
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
