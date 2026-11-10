<script lang="ts">
	import { asset } from '$app/paths';
	import { endpoints, parseFen } from '#lib/utils/board.js';

	let {
		fen,
		orientation,
		lastMove,
		bestMove,
		selectSquare,
		selected = [],
		disabled = false
	}: {
		fen: string;
		orientation: 'white' | 'black';
		lastMove?: string | null;
		bestMove?: string | null;
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
</script>

{#if squares}
	<div
		class="grid w-full max-w-lg grid-cols-[1.25rem_minmax(0,1fr)] rounded-xl border border-line bg-sidebar py-1.5 pr-1.5 shadow-lg shadow-black/25"
	>
		<div aria-hidden="true" class="grid grid-rows-8 text-center text-xs font-semibold text-muted">
			{#each squares.filter((_, i) => i % 8 === 0) as square (square.coordinate)}
				<span class="self-center">{square.coordinate[1]}</span>
			{/each}
		</div>
		<div
			role="group"
			aria-label={`Chessboard · ${orientation === 'white' ? 'White' : 'Black'} at bottom`}
			class="grid aspect-square min-w-0 grid-cols-8 grid-rows-8 overflow-hidden rounded-sm"
		>
			{#each squares as square (square.coordinate)}
				{@const piece = pieces[square.piece]}
				{@const isPlayed = played.includes(square.coordinate)}
				{@const isSuggested = suggested.includes(square.coordinate)}
				{@const isSelected = selected.includes(square.coordinate)}
				{@const classes = [
					'grid min-h-0 min-w-0 place-items-center',
					isSelected
						? 'bg-square-selected ring-2 ring-square-ink ring-inset'
						: isSuggested
							? 'bg-square-suggestion ring-2 ring-square-ink ring-inset'
							: isPlayed
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
								: ''}</span
						>
						{@render pieceImage(piece)}
					</div>
				{/if}
			{/each}
		</div>
		<div
			aria-hidden="true"
			class="col-start-2 grid grid-cols-8 pt-1 text-center text-xs font-semibold text-muted"
		>
			{#each squares.slice(-8) as square (square.coordinate)}
				<span>{square.coordinate[0]}</span>
			{/each}
		</div>
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
			class="pointer-events-none size-[94%] object-contain select-none"
		/>
	{/if}
{/snippet}
