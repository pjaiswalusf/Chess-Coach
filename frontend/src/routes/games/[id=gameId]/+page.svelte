<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { isProfile } from '#lib/api/review.js';
	import GameReview from '#lib/components/GameReview.svelte';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const requestedPly = $derived.by(() => {
		const ply = Number(page.url.searchParams.get('ply'));
		return Number.isSafeInteger(ply) && ply > 0 ? ply : 0;
	});
	const profile = $derived.by(() => {
		const value = page.url.searchParams.get('profile');
		return isProfile(value) ? value : null;
	});
</script>

<svelte:head><title>Game {data.id} · Chess Coach</title></svelte:head>
<div class="flex flex-wrap items-center justify-between gap-2">
	<h1 class="text-3xl font-semibold tracking-tight">Game review</h1>
	<a href={resolve('/games')} class="font-semibold text-accent underline">Back to Games</a>
</div>
{#key `${data.id}:${profile ?? ''}:${requestedPly}`}
	<GameReview id={data.id} {requestedPly} {profile} />
{/key}
