<script lang="ts">
	import type { ReviewRating } from '#lib/api/review.js';
	import { moveRatings } from '#lib/utils/review-rating.js';

	let { rating, large = false }: { rating: ReviewRating; large?: boolean } = $props();
	const mark = $derived(moveRatings[rating]);
	const paths: Record<string, string> = {
		book: 'M2 4c4 0 7 1 9 3v14c-2-2-5-3-9-3V4Zm20 0v14c-4 0-7 1-9 3V7c2-2 5-3 9-3Z',
		star: 'm12 1 3.2 6.7 7.4 1.1-5.3 5.2 1.2 7.3-6.5-3.5-6.5 3.5 1.2-7.3-5.3-5.2 7.4-1.1L12 1Z',
		thumb: 'M2 10h4v11H2zM8 10l4-8c2 0 3 1 3 3l-1 4h5a2 2 0 0 1 2 2.4l-1.5 8A2 2 0 0 1 17.5 21H8z',
		check: 'm2 12 3-3 4.5 4.5L19 4l3 3L9.5 19.5z',
		cross: 'm4 1 8 8 8-8 3 3-8 8 8 8-3 3-8-8-8 8-3-3 8-8-8-8z'
	};
	const path = $derived(paths[mark.symbol]);
</script>

<span
	aria-hidden="true"
	class={[
		'inline-grid shrink-0 place-items-center rounded-full bg-current leading-none font-black',
		large ? 'size-8 text-lg' : 'size-5 text-xs',
		mark.tone
	]}
>
	{#if path}
		<svg viewBox="0 0 24 24" fill="currentColor" class="size-[70%] text-white">
			<path d={path} />
		</svg>
	{:else}
		<span class="tracking-tighter text-white">{mark.symbol}</span>
	{/if}
</span>
