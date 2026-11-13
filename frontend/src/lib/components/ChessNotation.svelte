<script lang="ts">
	import { asset } from '$app/paths';

	let {
		text,
		color = 'white',
		variation = false,
		rated = false
	}: { text: string; color?: 'white' | 'black'; variation?: boolean; rated?: boolean } = $props();

	const pieces = {
		K: 'king',
		Q: 'queen',
		R: 'rook',
		B: 'bishop',
		N: 'knight'
	} as const;
	type Piece = keyof typeof pieces;
	const masks: Record<Piece, string> = {
		K: 'mask-[url(/pieces/chessnut/bK.svg)]',
		Q: 'mask-[url(/pieces/chessnut/bQ.svg)]',
		R: 'mask-[url(/pieces/chessnut/bR.svg)]',
		B: 'mask-[url(/pieces/chessnut/bB.svg)]',
		N: 'mask-[url(/pieces/chessnut/bN.svg)]'
	};

	// SAN already comes from the backend. Only the piece letters change on screen.
	const moves =
		/(?<!\w)([KQRBN][a-h1-8]{0,2}x?[a-h][1-8][+#]?|(?:[a-h]x)?[a-h][1-8](?:=[QRBN])?[+#]?|[O0](?:[-–][O0]){1,2}[+#]?)(?!\w)/g;
	const parts = $derived(text.split(moves));
	const startsWithBlack = $derived(variation ? /^\s*\d+\.\.\./.test(text) : color === 'black');
</script>

{#each parts as part, index (index)}
	{#if index % 2 === 0}{part}{:else}
		{@const pieceIndex = part.indexOf('=') + 1}
		{@const piece = part[pieceIndex] as Piece}
		{#if Object.hasOwn(pieces, piece)}
			{@const flip = variation && index % 4 === 3}
			{@const side = startsWithBlack !== flip ? 'b' : 'w'}
			{@const iconSize = 'inline-block size-[1.5em] align-[-0.36em]'}
			<span class="whitespace-nowrap"
				>{part.slice(0, pieceIndex)}{#if rated}<span
						role="img"
						aria-label={pieces[piece]}
						class={[iconSize, 'bg-current mask-contain mask-center mask-no-repeat', masks[piece]]}
					></span>{:else}<img
						src={asset(`pieces/chessnut/${side}${piece}.svg`)}
						alt={pieces[piece]}
						class={iconSize}
					/>{/if}{part.slice(pieceIndex + 1)}</span
			>
		{:else}{part}{/if}
	{/if}
{/each}
