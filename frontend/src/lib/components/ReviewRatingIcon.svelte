<script lang="ts">
	import type { ReviewRating } from '#lib/api/review.js';
	import { moveRatings } from '#lib/utils/review-rating.js';

	let { rating, large = false }: { rating: ReviewRating; large?: boolean } = $props();
	const mark = $derived(moveRatings[rating]);
</script>

<span
	aria-hidden="true"
	class={[
		'inline-grid shrink-0 place-items-center rounded-full bg-current leading-none font-black',
		large ? 'size-8 text-lg' : 'size-5 text-xs',
		mark.tone
	]}
>
	<span class="text-neutral-950">{mark.symbol}</span>
</span>
