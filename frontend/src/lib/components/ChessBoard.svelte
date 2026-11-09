<script lang="ts">
	import { endpoints, parseFen } from '#lib/utils/board.js';

	let {
		fen,
		orientation,
		lastMove,
		bestMove
	}: {
		fen: string;
		orientation: 'white' | 'black';
		lastMove?: string | null;
		bestMove?: string | null;
	} = $props();

	const pieces: Record<string, string> = {
		K: '♚',
		Q: '♛',
		R: '♜',
		B: '♝',
		N: '♞',
		P: '♟',
		k: '♚',
		q: '♛',
		r: '♜',
		b: '♝',
		n: '♞',
		p: '♟'
	};
	const squares = $derived(parseFen(fen, orientation));
	const played = $derived(endpoints(lastMove));
	const suggested = $derived(endpoints(bestMove));
</script>

{#if squares}
	<div
		role="group"
		aria-label={`Chessboard · ${orientation === 'white' ? 'White' : 'Black'} at bottom`}
		class="grid aspect-square w-full max-w-lg grid-cols-8 grid-rows-8 overflow-hidden rounded-lg border border-slate-700"
	>
		{#each squares as square, i (square.coordinate)}
			{@const isPlayed = played.includes(square.coordinate)}
			{@const isSuggested = suggested.includes(square.coordinate)}
			<div
				class={[
					'relative grid min-h-0 min-w-0 place-items-center font-serif leading-none',
					isSuggested
						? 'bg-sky-300 ring-2 ring-sky-900 ring-inset'
						: isPlayed
							? 'bg-amber-400 ring-2 ring-amber-900 ring-inset'
							: square.dark
								? 'bg-emerald-700'
								: 'bg-emerald-100'
				]}
				data-square={square.coordinate}
				title={square.label}
			>
				<span class="sr-only"
					>{square.label}{isPlayed ? ' · Played move' : ''}{isSuggested
						? ' · Engine suggestion'
						: ''}</span
				>
				{#if i % 8 === 0}
					<span
						aria-hidden="true"
						class={[
							'absolute top-0.5 left-0.5 font-sans text-[0.6rem] font-bold',
							square.dark && !isPlayed && !isSuggested ? 'text-white' : 'text-slate-900'
						]}>{square.coordinate[1]}</span
					>
				{/if}
				{#if i >= 56}
					<span
						aria-hidden="true"
						class={[
							'absolute right-0.5 bottom-0.5 font-sans text-[0.6rem] font-bold',
							square.dark && !isPlayed && !isSuggested ? 'text-white' : 'text-slate-900'
						]}>{square.coordinate[0]}</span
					>
				{/if}
				<span
					aria-hidden="true"
					class={[
						'text-[clamp(1.1rem,6vw,2.6rem)]',
						square.piece === square.piece.toUpperCase()
							? 'text-white [text-shadow:0_1px_2px_#0f172a,0_-1px_2px_#0f172a]'
							: 'text-slate-950'
					]}
				>
					{pieces[square.piece] ?? ''}
				</span>
			</div>
		{/each}
	</div>
{:else}
	<p role="alert" class="rounded-lg bg-amber-100 p-4 text-amber-950">
		Position cannot be displayed. Refresh the analysis or check the stored game.
	</p>
{/if}
