<script lang="ts">
	import { asset } from '$app/paths';
	import type { ReviewRating } from '#lib/api/review.js';
	import { endpoints, parseFen } from '#lib/utils/board.js';
	import { moveRatings } from '#lib/utils/review-rating.js';
	import ReviewRatingIcon from './ReviewRatingIcon.svelte';

	let {
		fen,
		orientation,
		lastMove,
		lastMoveRating,
		bestMove,
		review = false,
		selectSquare,
		selected = [],
		disabled = false
	}: {
		fen: string;
		orientation: 'white' | 'black';
		lastMove?: string | null;
		lastMoveRating?: ReviewRating;
		bestMove?: string | null;
		review?: boolean;
		selectSquare?: (square: string) => void;
		selected?: string[];
		disabled?: boolean;
	} = $props();

	type PieceAsset = Parameters<typeof asset>[0];
	const pieces: Partial<Record<string, PieceAsset>> = {
		K: 'pieces/chessnut/wK.svg',
		Q: 'pieces/chessnut/wQ.svg',
		R: 'pieces/chessnut/wR.svg',
		B: 'pieces/chessnut/wB.svg',
		N: 'pieces/chessnut/wN.svg',
		P: 'pieces/chessnut/wP.svg',
		k: 'pieces/chessnut/bK.svg',
		q: 'pieces/chessnut/bQ.svg',
		r: 'pieces/chessnut/bR.svg',
		b: 'pieces/chessnut/bB.svg',
		n: 'pieces/chessnut/bN.svg',
		p: 'pieces/chessnut/bP.svg'
	};
	const squares = $derived(parseFen(fen, orientation));
	const played = $derived(endpoints(lastMove));
	const suggested = $derived(endpoints(bestMove));
	const mark = $derived(lastMoveRating ? moveRatings[lastMoveRating] : null);
</script>

{#if squares}
	<div
		class={[
			'w-full shadow-lg shadow-black/25',
			review
				? 'overflow-hidden rounded-md'
				: 'grid max-w-lg grid-cols-[1.25rem_minmax(0,1fr)] rounded-xl border border-line bg-sidebar py-1.5 pr-1.5'
		]}
	>
		{#if !review}
			<div aria-hidden="true" class="grid grid-rows-8 text-center text-xs font-semibold text-muted">
				{#each squares.filter((_, i) => i % 8 === 0) as square (square.coordinate)}
					<span class="self-center">{square.coordinate[1]}</span>
				{/each}
			</div>
		{/if}
		<div
			role="group"
			aria-label={`Chessboard · ${orientation === 'white' ? 'White' : 'Black'} at bottom`}
			class="grid aspect-square min-w-0 grid-cols-8 grid-rows-8 overflow-hidden rounded-sm"
		>
			{#each squares as square, index (square.coordinate)}
				{@const piece = pieces[square.piece]}
				{@const isPlayed = played.includes(square.coordinate)}
				{@const isRatedDestination = !!mark && square.coordinate === played[1]}
				{@const isSuggested = suggested.includes(square.coordinate)}
				{@const isSelected = selected.includes(square.coordinate)}
				{@const classes = [
					'relative grid min-h-0 min-w-0 place-items-center',
					isSelected
						? 'bg-square-selected ring-2 ring-square-ink ring-inset'
						: isSuggested
							? 'bg-square-suggestion ring-2 ring-square-ink ring-inset'
							: isPlayed && !mark
								? 'bg-square-played ring-2 ring-square-ink ring-inset'
								: square.dark
									? 'bg-square-dark'
									: 'bg-square-light'
				]}
				{#if selectSquare}
					<button
						type="button"
						{disabled}
						class={[
							classes,
							'focus-visible:z-10 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-square-ink enabled:cursor-pointer enabled:hover:brightness-110'
						]}
						data-square={square.coordinate}
						aria-label={square.label}
						aria-pressed={isSelected}
						onclick={() => selectSquare?.(square.coordinate)}
					>
						{@render pieceImage(piece)}
					</button>
				{:else}
					<div class={classes} data-square={square.coordinate} title={square.label}>
						<span class="sr-only"
							>{square.label}{isPlayed ? ' · Played move' : ''}{isSuggested
								? ' · Engine suggestion'
								: ''}{isRatedDestination ? ' · ' + mark?.label : ''}</span
						>
						{#if isPlayed && mark}
							<span
								aria-hidden="true"
								class={['pointer-events-none absolute inset-0 bg-current opacity-65', mark.tone]}
							></span>
						{/if}
						{@render pieceImage(piece)}
						{#if isRatedDestination && lastMoveRating}
							<span
								title={mark?.label}
								class="absolute top-0.5 right-0.5 origin-top-right scale-75 leading-none sm:scale-100"
							>
								<ReviewRatingIcon rating={lastMoveRating} />
							</span>
						{/if}
						{#if review}
							{@const coordinateColor =
								square.dark && !isPlayed && !isSuggested ? 'text-square-light' : 'text-square-ink'}
							{#if index % 8 === 0}
								<span
									aria-hidden="true"
									class={[
										'pointer-events-none absolute top-0.5 left-1 text-[0.65rem] font-bold sm:text-xs',
										coordinateColor
									]}>{square.coordinate[1]}</span
								>
							{/if}
							{#if index >= 56}
								<span
									aria-hidden="true"
									class={[
										'pointer-events-none absolute right-1 bottom-0.5 text-[0.65rem] font-bold sm:text-xs',
										coordinateColor
									]}>{square.coordinate[0]}</span
								>
							{/if}
						{/if}
					</div>
				{/if}
			{/each}
		</div>
		{#if !review}<div
				aria-hidden="true"
				class="col-start-2 grid grid-cols-8 pt-1 text-center text-xs font-semibold text-muted"
			>
				{#each squares.slice(-8) as square (square.coordinate)}
					<span>{square.coordinate[0]}</span>
				{/each}
			</div>{/if}
	</div>
{:else}
	<p role="alert" class="rounded-lg bg-warning-surface p-4 text-warning">
		Position cannot be displayed. Refresh the analysis or check the stored game.
	</p>
{/if}

{#snippet pieceImage(piece: PieceAsset | undefined)}
	{#if piece}
		<img
			src={asset(piece)}
			alt=""
			width="800"
			height="800"
			draggable="false"
			class="pointer-events-none relative size-[94%] object-contain select-none"
		/>
	{/if}
{/snippet}
