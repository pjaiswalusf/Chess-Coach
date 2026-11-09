<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { SvelteURLSearchParams } from 'svelte/reactivity';
	import { getGames, type GameQuery } from '#lib/api/games.js';
	import { asyncRead } from '#lib/async-read.svelte.js';
	import { formatDate, results } from '#lib/utils/display.js';
	import Button from '#lib/components/ui/Button.svelte';
	import Card from '#lib/components/ui/Card.svelte';
	import EmptyState from '#lib/components/ui/EmptyState.svelte';
	import ErrorMessage from '#lib/components/ui/ErrorMessage.svelte';
	import Spinner from '#lib/components/ui/Spinner.svelte';
	import StatusBadge from '#lib/components/ui/StatusBadge.svelte';

	const limit = 25;
	const times = ['bullet', 'blitz', 'rapid', 'daily'] as const;
	const colors = ['white', 'black'] as const;
	const outcomes = ['win', 'loss', 'draw'] as const;
	const filterControls = [
		{ key: 'time_class', name: 'Time control', values: times },
		{ key: 'player_color', name: 'Player color', values: colors },
		{ key: 'result', name: 'Result', values: outcomes }
	] as const;
	function choice<T extends string>(options: readonly T[], key: string) {
		return options.find((value) => value === page.url.searchParams.get(key));
	}
	const filters = $derived<GameQuery>({
		time_class: choice(times, 'time_class'),
		player_color: choice(colors, 'player_color'),
		result: choice(outcomes, 'result')
	});
	const offset = $derived.by(() => {
		const value = Number(page.url.searchParams.get('offset'));
		return Number.isSafeInteger(value) && value >= 0 && value % limit === 0 ? value : 0;
	});
	const games = asyncRead(
		(signal) => getGames(signal, { limit, offset, ...filters }),
		'Check the local backend and retry.',
		undefined,
		() => page.url.search
	);

	function navigate(next: number, key?: keyof GameQuery, value?: string) {
		const params = new SvelteURLSearchParams(page.url.search);
		if (key) {
			if (value) params.set(key, value);
			else params.delete(key);
		}
		if (next > 0) params.set('offset', String(next));
		else params.delete('offset');
		const target = params.size ? (`/games?${params}` as const) : '/games';
		void goto(resolve(target), { reset: false });
	}

	const hasFilters = $derived(
		Boolean(filters.time_class || filters.player_color || filters.result)
	);
</script>

<svelte:head><title>Games · Chess Coach</title></svelte:head>

<div class="flex flex-wrap items-baseline justify-between gap-3">
	<h1 class="text-3xl font-semibold tracking-tight">Games</h1>
	<a href={resolve('/games/analysis')} class="font-medium text-emerald-800 underline"
		>Analysis runs</a
	>
</div>

<Card>
	<div class="flex flex-wrap gap-4">
		{#each filterControls as { key, name, values } (key)}
			<label class="flex flex-col gap-1 text-sm font-medium">
				{name}
				<select
					class="min-w-32 rounded-lg border-slate-300"
					value={filters[key] ?? ''}
					onchange={(event) => navigate(0, key, event.currentTarget.value)}
				>
					<option value="">All</option>
					{#each values as value (value)}<option {value} class="capitalize">{value}</option>{/each}
				</select>
			</label>
		{/each}
	</div>
</Card>

{#if games.state.status === 'loading'}
	<Spinner label="Loading games…" />
{:else if games.state.status === 'error'}
	<ErrorMessage title="Unable to load games." message={games.state.message} retry={games.refresh} />
{:else if games.state.status === 'success'}
	{@const data = games.state.data}
	{#if !data.items.length}
		{#if offset > 0}
			<EmptyState title="This page has no games.">
				<Button onclick={() => navigate(0)}>Return to first page</Button>
			</EmptyState>
		{:else if hasFilters}
			<EmptyState title="No games match these filters.">
				<a href={resolve('/games')} class="font-medium text-emerald-800 underline">Clear filters</a>
			</EmptyState>
		{:else}
			<EmptyState title="No games imported yet.">
				<p>Visit Sync to import your completed games.</p>
				<a href={resolve('/sync')} class="font-medium text-emerald-800 underline">Go to Sync</a>
			</EmptyState>
		{/if}
	{:else}
		<Card>
			<h2 class="text-lg font-semibold">Completed games</h2>
			<p role="status" class="text-sm text-slate-700">
				Showing {data.offset + 1}–{data.offset + data.items.length} of {data.total} games
			</p>
			<div class="overflow-x-auto">
				<table class="w-full text-left text-sm">
					<thead class="border-b border-slate-200 text-slate-700">
						<tr>
							{#each ['Opponent', 'Date', 'Played as', 'Result', 'Rating', 'Time control', 'Opening', 'Critical errors', 'Analysis'] as name (name)}
								<th scope="col" class="p-2 whitespace-nowrap">{name}</th>
							{/each}
						</tr>
					</thead>
					<tbody class="divide-y divide-slate-200">
						{#each data.items as game (game.id)}
							<tr>
								<th scope="row" class="p-2">
									<a
										href={resolve('/games/[id]', { id: String(game.id) })}
										class="font-semibold text-emerald-800 underline">vs {game.opponent}</a
									>
								</th>
								<td class="p-2 whitespace-nowrap">{formatDate(game.played_at)}</td>
								<td class="p-2 capitalize">{game.player_color}</td>
								<td class="p-2">{results[game.result]}</td>
								<td class="p-2">{game.player_rating ?? 'Unknown'}</td>
								<td class="p-2 capitalize">{game.time_class ?? 'Unknown'}</td>
								<td class="p-2">{game.opening_name ?? 'Unknown'}</td>
								<td class="p-2">{game.critical_errors ?? 'Unavailable'}</td>
								<td class="p-2"
									><StatusBadge
										label={game.analysis_status}
										tone={game.analysis_status === 'completed'
											? 'positive'
											: game.analysis_status === 'failed' || game.analysis_status === 'incompatible'
												? 'caution'
												: 'neutral'}
									/></td
								>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			<nav aria-label="Games pages" class="flex gap-2">
				<Button
					onclick={() => navigate(Math.max(0, data.offset - limit))}
					disabled={data.offset === 0}>Previous</Button
				>
				<Button
					onclick={() => navigate(data.offset + limit)}
					disabled={data.offset + data.items.length >= data.total}>Next</Button
				>
			</nav>
		</Card>
	{/if}
{/if}
