<script lang="ts">
	import { resolve } from '$app/paths';
	import { getOverview } from '#lib/api/analytics.js';
	import { getGames } from '#lib/api/games.js';
	import { getSystem } from '#lib/api/system.js';
	import { asyncRead } from '#lib/async-read.svelte.js';
	import Card from '#lib/components/ui/Card.svelte';
	import Button from '#lib/components/ui/Button.svelte';
	import ErrorMessage from '#lib/components/ui/ErrorMessage.svelte';
	import MetricCard from '#lib/components/ui/MetricCard.svelte';
	import Spinner from '#lib/components/ui/Spinner.svelte';
	import ProgressEvidence from '#lib/components/ProgressEvidence.svelte';
	import WeaknessList from '#lib/components/WeaknessList.svelte';
	import { formatDate, formatRate, results, words } from '#lib/utils/display.js';

	const overview = asyncRead(getOverview, 'Check the local database and retry.');
	const library = asyncRead(getSystem, 'Check the local database and retry.');
	const recent = asyncRead(
		(signal) => getGames(signal, { limit: 5 }),
		'Check the backend and retry.'
	);
</script>

<svelte:head><title>Dashboard · Chess Coach</title></svelte:head>

<div class="flex flex-wrap items-center justify-between gap-3">
	<h1 class="text-3xl font-semibold tracking-tight">Dashboard</h1>
	<a href={resolve('/sync')} class="font-semibold text-emerald-800 underline"
		>Import and analyze games</a
	>
</div>

{#if library.state.status === 'loading'}
	<Spinner label="Loading library totals…" />
{:else if library.state.status === 'error'}
	<ErrorMessage
		title="Unable to load library totals."
		message={library.state.message}
		retry={library.refresh}
	/>
{:else if library.state.status === 'success'}
	{@const totals = library.state.data.statistics}
	{#if totals}
		<h2 class="text-lg font-semibold">Local library totals</h2>
		<div class="grid gap-3 sm:grid-cols-3">
			<MetricCard label="Games imported" value={totals.games_stored} />
			<MetricCard label="Games analyzed" value={totals.games_analyzed} />
			<MetricCard label="Without completed analysis" value={totals.pending_games} />
		</div>
	{:else}
		<ErrorMessage
			title="Library totals unavailable."
			message="Check database access on the System page."
			retry={library.refresh}
		/>
	{/if}
{/if}

<Card>
	<h2 class="text-lg font-semibold">Recent completed games</h2>
	{#if recent.state.status === 'loading'}
		<Spinner label="Loading recent games…" />
	{:else if recent.state.status === 'error'}
		<ErrorMessage
			title="Unable to load recent games."
			message={recent.state.message}
			retry={recent.refresh}
		/>
	{:else if recent.state.status === 'success'}
		{#if recent.state.data.items.length}
			<ul class="divide-y divide-slate-200">
				{#each recent.state.data.items as game (game.id)}
					<li class="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2">
						<a
							href={resolve('/games/[id]', { id: String(game.id) })}
							class="font-medium break-all text-emerald-800 underline">vs {game.opponent}</a
						>
						<span class="text-sm text-slate-700"
							>{formatDate(game.played_at)} · <span class="capitalize">{game.player_color}</span> · {results[
								game.result
							]} · <span class="capitalize">{game.analysis_status}</span></span
						>
					</li>
				{/each}
			</ul>
			<a href={resolve('/games')} class="text-sm font-medium text-emerald-800 underline"
				>Browse all games</a
			>
		{:else}
			<p>No games imported yet. Visit Sync to get started.</p>
		{/if}
	{/if}
</Card>

{#if overview.state.status === 'loading'}
	<Spinner label="Loading performance…" />
{:else if overview.state.status === 'error'}
	<ErrorMessage
		title="Unable to load performance."
		message={overview.state.message}
		retry={overview.refresh}
	/>
{:else if overview.state.status === 'success'}
	{@const report = overview.state.data}
	<Card>
		<div class="flex flex-wrap items-center justify-between gap-2">
			<h2 class="text-lg font-semibold">Tracked player performance · Last 50 games</h2>
			<Button onclick={overview.refresh}>Refresh performance</Button>
		</div>
		{#if report.status === 'NO_GAMES'}
			<p>Import and analyze completed games to see performance here.</p>
		{:else}
			<p>
				{report.health?.analyzed_games} analyzed of {report.health?.selected_games} selected games · All
				colors and time controls
			</p>
			{#if report.status === 'PARTIAL'}<p>
					Some games in this window lack completed analysis.
				</p>{/if}
			{#if report.metrics && report.metrics.moves.mean_loss_cp !== null}
				<p>
					Mean loss: {formatRate(report.metrics.moves.mean_loss_cp)} cp per comparable move ({report
						.metrics.moves.comparable_moves} moves)
				</p>
			{:else}
				<p>No comparable move analysis yet.</p>
			{/if}
			<h3 class="font-semibold">Performance by phase</h3>
			<dl class="grid gap-3 sm:grid-cols-3">
				{#each ['opening', 'middlegame', 'endgame'] as phase (phase)}
					{@const segment = report.phases.find((item) => item.key === phase)}
					{@const rate = segment?.summary.moves.significant}
					<div class="rounded-lg bg-slate-100 p-3">
						<dt class="font-medium capitalize">{phase}</dt>
						<dd class="text-sm">
							{segment?.evidence_status === 'sufficient' && rate?.per_100 != null
								? `${formatRate(rate.per_100)} significant errors per 100 classifiable player moves (${rate.denominator} moves)`
								: 'Insufficient evidence'}
						</dd>
					</div>
				{/each}
			</dl>
		{/if}
	</Card>
	<Card>
		<h2 class="text-lg font-semibold">Recurring weaknesses</h2>
		<p class="text-sm text-slate-700">Up to three supported weaknesses per category.</p>
		<WeaknessList patterns={report.patterns} />
		<a href={resolve('/coach')} class="font-medium text-emerald-800 underline"
			>Explore coaching evidence</a
		>
	</Card>
	<Card>
		<h2 class="text-lg font-semibold">Openings to review</h2>
		{@const ranked = report.patterns.opening ?? []}
		{#if ranked.length}
			<ul class="space-y-2">
				{#each ranked.slice(0, 3) as pattern (pattern.candidate_key)}
					{@const opening = report.openings.find(
						(item) => pattern.candidate_key === `opening:${item.key}`
					)}
					<li>
						{opening
							? `ECO ${opening.key}${opening.opening_names.length === 1 ? ' · ' + opening.opening_names[0] : ''}`
							: words(pattern.candidate_key)} · {pattern.distinct_games} games · {pattern.significant_errors}
						significant and {pattern.critical_errors} critical errors in {pattern.opportunities} opportunities
					</li>
				{/each}
			</ul>
		{:else}
			<p>Insufficient evidence to flag a recurring opening problem.</p>
		{/if}
		<ProgressEvidence
			conversion={report.conversion}
			conversion_strength={report.conversion_strength}
			recent_trends={report.recent_trends}
		/>
	</Card>
{/if}
