<script lang="ts">
	import type { PublicPuzzle } from '#lib/api/training.js';
	import ChessBoard from '#lib/components/ChessBoard.svelte';
	import Button from '#lib/components/ui/Button.svelte';

	let {
		puzzle,
		disabled = false,
		solution,
		onMove
	}: {
		puzzle: PublicPuzzle;
		disabled?: boolean;
		solution?: string;
		onMove: (uci: string | null) => void;
	} = $props();

	const promotionNames: Record<string, string> = {
		q: 'Queen',
		r: 'Rook',
		b: 'Bishop',
		n: 'Knight'
	};
	let from = $state('');
	let to = $state('');
	let promotion = $state('');
	const choices = $derived(
		from && to ? puzzle.legal_moves.filter((move) => move.startsWith(from + to)) : []
	);

	function selectSquare(square: string) {
		if (disabled) return;
		if (from && !to && puzzle.legal_moves.some((move) => move.startsWith(from + square))) {
			to = square;
			const chosen = puzzle.legal_moves.find((move) => move === from + square);
			onMove(chosen ?? null);
			return;
		}
		from = puzzle.legal_moves.some((move) => move.startsWith(square)) ? square : from;
		to = '';
		promotion = '';
		onMove(null);
	}

	function reset() {
		from = '';
		to = '';
		promotion = '';
		onMove(null);
	}
</script>

<ChessBoard
	fen={puzzle.fen}
	orientation={puzzle.side_to_move}
	{selectSquare}
	selected={solution ? [] : [from, to]}
	bestMove={solution}
	{disabled}
/>

{#if !solution}
	{#if puzzle.legal_moves.length > 0}<p role="status" class="text-sm text-muted">
			{#if to}Selected {from} to {to}.{:else if from}Select a destination for {from}.{:else}Select a
				piece to move.{/if}
		</p>{/if}
	{#if choices.some((move) => move.length === 5)}
		<label class="flex items-center gap-2 text-sm">
			Promote to
			<select
				class="rounded-md border-control-line bg-canvas text-ink focus:border-accent focus:ring-accent"
				value={promotion}
				{disabled}
				onchange={(event) => {
					promotion = event.currentTarget.value;
					onMove(promotion || null);
				}}
			>
				<option value="">Choose a piece</option>
				{#each choices as move (move)}
					<option value={move}>{promotionNames[move[4]]}</option>
				{/each}
			</select>
		</label>
	{/if}
	{#if from && !disabled}
		<Button onclick={reset}>Clear selection</Button>
	{/if}
{/if}
