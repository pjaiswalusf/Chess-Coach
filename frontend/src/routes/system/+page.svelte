<script lang="ts">
	import { getSystem } from '#lib/api/system.js';
	import { asyncRead } from '#lib/async-read.svelte.js';
	import Button from '#lib/components/ui/Button.svelte';
	import Card from '#lib/components/ui/Card.svelte';
	import ErrorMessage from '#lib/components/ui/ErrorMessage.svelte';
	import MetricCard from '#lib/components/ui/MetricCard.svelte';
	import Spinner from '#lib/components/ui/Spinner.svelte';
	import StatusBadge from '#lib/components/ui/StatusBadge.svelte';

	const system = asyncRead(getSystem, 'Check the local backend and retry.');
	const services = [
		{ key: 'database', label: 'Database' },
		{ key: 'stockfish', label: 'Stockfish' },
		{ key: 'ollama', label: 'Ollama' }
	] as const;
	const labels = {
		available: 'Available',
		unavailable: 'Unavailable',
		unknown: 'Unknown'
	} as const;
	const tones = { available: 'positive', unavailable: 'negative', unknown: 'caution' } as const;
</script>

<svelte:head><title>System · Chess Coach</title></svelte:head>

<div class="flex flex-wrap items-center justify-between gap-3">
	<h1 class="text-3xl font-semibold tracking-tight">System</h1>
	<Button onclick={system.refresh} loading={system.state.status === 'loading'}
		>Refresh status</Button
	>
</div>

{#if system.state.status === 'loading'}
	<Spinner label="Loading system status…" />
{:else if system.state.status === 'error'}
	<ErrorMessage
		title="Unable to load system status."
		message={system.state.message}
		retry={system.refresh}
	/>
{:else if system.state.status === 'success'}
	{@const { components, statistics, status } = system.state.data}
	<Card>
		<div class="flex flex-wrap items-center justify-between gap-2">
			<h2 class="text-lg font-semibold">Local services</h2>
			<StatusBadge
				label={status === 'healthy'
					? 'Healthy'
					: status === 'degraded'
						? 'Degraded'
						: 'Unavailable'}
				tone={status === 'healthy' ? 'positive' : status === 'degraded' ? 'caution' : 'negative'}
			/>
		</div>
		<dl class="divide-y divide-slate-200">
			{#each services as service (service.key)}
				{@const component = components[service.key]}
				<div class="grid grid-cols-[1fr_auto] items-center gap-2 py-3">
					<dt class="font-medium">{service.label}</dt>
					<dd><StatusBadge label={labels[component.status]} tone={tones[component.status]} /></dd>
					{#if service.key === 'database' && component.status === 'unavailable'}
						<dd class="col-span-2 text-sm text-slate-600">
							Check database access and apply pending migrations.
						</dd>
					{:else if service.key === 'stockfish' && component.status !== 'available'}
						<dd class="col-span-2 text-sm text-slate-600">
							Check your Stockfish installation and start the local analysis worker.
						</dd>
					{:else if service.key === 'ollama' && component.status !== 'available'}
						<dd class="col-span-2 text-sm text-slate-600">
							Start Ollama and check that the configured model is installed.
						</dd>
					{/if}
				</div>
			{/each}
		</dl>
	</Card>
	{#if statistics}
		<div class="grid gap-3 sm:grid-cols-3">
			<MetricCard label="Games stored" value={statistics.games_stored} />
			<MetricCard label="Games analyzed" value={statistics.games_analyzed} />
			<MetricCard label="Games pending" value={statistics.pending_games} />
		</div>
	{:else}
		<p class="text-slate-600">Game counts are unavailable.</p>
	{/if}
{/if}
