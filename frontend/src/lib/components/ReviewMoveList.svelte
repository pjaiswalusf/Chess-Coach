<script lang="ts">
	import type { ReviewMove } from '#lib/api/review.js';
	import { moveRatings } from '#lib/utils/review-rating.js';
	import ReviewRatingIcon from './ReviewRatingIcon.svelte';

	let {
		moves,
		selected,
		onSelect
	}: {
		moves: ReviewMove[];
		selected?: number;
		onSelect: (ply: number) => void;
	} = $props();

	const turns = $derived.by(() => {
		const rows: { number: number; white?: ReviewMove; black?: ReviewMove }[] = [];
		for (const move of moves) {
			let row = rows.at(-1);
			if (!row || row.number !== move.move_number) {
				row = { number: move.move_number };
				rows.push(row);
			}
			row[move.mover === 'white' ? 'white' : 'black'] = move;
		}
		return rows;
	});
	let list = $state<HTMLDivElement>();

	$effect(() => {
		if (!list || selected === undefined) return;
		const active = list.querySelector(`[data-ply="${selected}"]`);
		if (!active) return;
		const row = active.getBoundingClientRect();
		const viewport = list.getBoundingClientRect();
		if (row.top < viewport.top) list.scrollTop -= viewport.top - row.top;
		else if (row.bottom > viewport.bottom) list.scrollTop += row.bottom - viewport.bottom;
	});
</script>

{#if turns.length}
	<div
		bind:this={list}
		class="max-h-52 overflow-y-auto overscroll-contain rounded-lg border border-line"
	>
		<table class="w-full table-fixed text-sm" aria-label="Move notation">
			<thead class="bg-sidebar text-left text-xs text-muted">
				<tr>
					<th scope="col" class="w-14 px-3 py-1.5">Move</th>
					<th scope="col" class="px-2 py-1.5">White</th>
					<th scope="col" class="px-2 py-1.5">Black</th>
				</tr>
			</thead>
			<tbody>
				{#each turns as { number, white, black } (number)}
					<tr class="odd:bg-white/5">
						<th scope="row" class="px-3 text-left font-medium text-muted tabular-nums">{number}.</th
						>
						<td class="p-0.5">{@render moveButton(white)}</td>
						<td class="p-0.5">{@render moveButton(black)}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{:else}
	<p class="px-4 py-3 text-sm text-muted">This completed game has no recorded moves.</p>
{/if}

{#snippet moveButton(move: ReviewMove | undefined)}
	{#if move}
		{@const mark = moveRatings[move.rating]}
		<button
			type="button"
			data-ply={move.ply}
			aria-pressed={selected === move.ply}
			title={mark.label}
			onclick={() => onSelect(move.ply)}
			class={[
				'flex w-full items-center gap-2 rounded px-2 py-1.5 text-left font-bold hover:bg-raised focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent aria-pressed:bg-raised aria-pressed:ring-1 aria-pressed:ring-control-line aria-pressed:ring-inset',
				mark.tone
			]}
		>
			<ReviewRatingIcon rating={move.rating} />
			{move.played_move_san}
			<span class="sr-only">{mark.label}</span>
		</button>
	{/if}
{/snippet}
