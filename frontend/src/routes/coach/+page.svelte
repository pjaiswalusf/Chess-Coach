<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { getPatterns, type Window } from '#lib/api/analytics.js';
	import { isProfile } from '#lib/api/review.js';
	import { asyncRead } from '#lib/async-read.svelte.js';
	import HistoricalCoaching from '#lib/components/HistoricalCoaching.svelte';
	import ProgressEvidence from '#lib/components/ProgressEvidence.svelte';
	import WeaknessList from '#lib/components/WeaknessList.svelte';
	import Button from '#lib/components/ui/Button.svelte';
	import Card from '#lib/components/ui/Card.svelte';
	import EmptyState from '#lib/components/ui/EmptyState.svelte';
	import ErrorMessage from '#lib/components/ui/ErrorMessage.svelte';
	import Spinner from '#lib/components/ui/Spinner.svelte';

	const options = [
		{ value: 'last_20', label: 'Last 20 games' },
		{ value: 'last_50', label: 'Last 50 games' },
		{ value: 'last_100', label: 'Last 100 games' },
		{ value: 'all', label: 'All games' }
	] as const;
	const window = $derived<Window>(
		options.find(({ value }) => value === page.url.searchParams.get('window'))?.value ?? 'last_50'
	);
	const evidence = asyncRead(
		(signal) => getPatterns(window, signal),
		'Check the local backend and retry.',
		undefined,
		() => window
	);

	function selectWindow(value: string) {
		const next = options.find((item) => item.value === value);
		if (next) void goto(resolve(`/coach?window=${next.value}`), { reset: false });
	}
</script>

<svelte:head><title>Coach · Chess Coach</title></svelte:head>
<h1 class="text-3xl font-semibold tracking-tight">Coach</h1>
<p>
	Review recurring patterns in your completed games and practice with the positions that support
	them.
</p>

<Card>
	<div class="flex flex-wrap items-end gap-3">
		<label class="grid gap-1 text-sm font-medium">
			Analysis window
			<select
				class="rounded-lg border-slate-300"
				value={window}
				onchange={(event) => selectWindow(event.currentTarget.value)}
			>
				{#each options as option (option.value)}<option value={option.value}>{option.label}</option
					>{/each}
			</select>
		</label>
		<Button onclick={evidence.refresh} loading={evidence.state.status === 'loading'}
			>Refresh report</Button
		>
	</div>
</Card>

{#if evidence.state.status === 'loading'}
	<Spinner label="Loading historical evidence…" />
{:else if evidence.state.status === 'error'}
	<ErrorMessage
		title="Unable to load historical evidence."
		message={evidence.state.message}
		retry={evidence.refresh}
	/>
{:else if evidence.state.status === 'success'}
	{@const report = evidence.state.data}
	{#if report.status === 'NO_GAMES'}
		<EmptyState title="No completed games in this window.">
			<p>Import and analyze completed games to see historical coaching.</p>
			<a href={resolve('/sync')} class="font-semibold text-emerald-800 underline">Go to Sync</a>
		</EmptyState>
	{:else}
		<Card>
			<h2 class="text-lg font-semibold">Measured evidence</h2>
			<p>
				{report.health?.analyzed_games} analyzed of {report.health?.selected_games} selected games · {report
					.health?.analyzed_player_moves} analyzed player moves
			</p>
			<p class="text-sm text-slate-700">
				All colors and time controls · {report.analytics_version} / {report.policy_version}
			</p>
			{#if report.status === 'PARTIAL'}<p>
					Some selected games lack compatible analysis. Analyze pending games to improve coverage.
				</p>{/if}
			<h3 class="font-semibold">Recurring weaknesses by category</h3>
			<WeaknessList patterns={report.patterns} examples profile={report.profile_hash} />
		</Card>
		<Card>
			<h2 class="text-lg font-semibold">Results over time</h2>
			<ProgressEvidence
				conversion={report.conversion}
				conversion_strength={report.conversion_strength}
				recent_trends={report.recent_trends}
			/>
		</Card>
		{#if isProfile(report.profile_hash) && isProfile(report.report_hash) && Object.values(report.patterns).some((rows) => rows.length)}
			{#key `${window}:${report.profile_hash}`}
				<HistoricalCoaching
					{window}
					profile={report.profile_hash}
					{report}
					refresh={evidence.refresh}
				/>
			{/key}
		{:else}
			<Card
				><h2 class="text-lg font-semibold">Coach interpretation and practice</h2>
				<p>Coaching needs a recurring weakness supported by analyzed games.</p></Card
			>
		{/if}
	{/if}
{/if}
