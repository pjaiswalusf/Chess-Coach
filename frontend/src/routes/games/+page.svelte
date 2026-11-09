<script lang="ts">
	import { resolve } from '$app/paths';
	import { getGames } from '#lib/api/games.js';
	import { asyncRead } from '#lib/async-read.svelte.js';
	import Card from '#lib/components/ui/Card.svelte';
	import EmptyState from '#lib/components/ui/EmptyState.svelte';
	import ErrorMessage from '#lib/components/ui/ErrorMessage.svelte';
	import Spinner from '#lib/components/ui/Spinner.svelte';

	const games = asyncRead(
		getGames,
		'Check the local backend and retry.',
		(page) => !page.items.length
	);
</script>

<svelte:head><title>Games · Chess Coach</title></svelte:head>

<div class="flex flex-wrap items-baseline justify-between gap-3">
	<h1 class="text-3xl font-semibold tracking-tight">Games</h1>
	<a
		href={resolve('/games/analysis')}
		class="font-medium text-emerald-800 underline underline-offset-4">Analysis runs</a
	>
</div>

{#if games.state.status === 'loading'}
	<Spinner label="Loading games…" />
{:else if games.state.status === 'error'}
	<ErrorMessage title="Unable to load games." message={games.state.message} retry={games.refresh} />
{:else if games.state.status === 'empty'}
	<EmptyState title="No games imported yet.">
		<p class="text-slate-600">Visit Sync to import your completed games.</p>
		<a href={resolve('/sync')} class="font-medium text-emerald-800 underline underline-offset-4"
			>Go to Sync</a
		>
	</EmptyState>
{:else}
	<Card>
		<h2 class="text-lg font-semibold">Recent completed games</h2>
		<p class="text-sm text-slate-600">
			Showing {games.state.data.items.length} of {games.state.data.total} games
		</p>
		<ul class="divide-y divide-slate-200">
			{#each games.state.data.items as game (game.id)}
				<li class="flex flex-wrap justify-between gap-x-4 gap-y-1 py-2">
					<span class="min-w-0 break-words">vs {game.opponent}</span>
					<span class="text-slate-700">
						{{ win: 'Win', loss: 'Loss', draw: 'Draw', unknown: 'Unknown' }[game.result]}
					</span>
				</li>
			{/each}
		</ul>
	</Card>
{/if}
