<script lang="ts">
	import { getHealth } from '#lib/api/health.js';
	import { getSystem } from '#lib/api/system.js';
	import { asyncRead } from '#lib/async-read.svelte.js';
	import Button from '#lib/components/ui/Button.svelte';
	import Card from '#lib/components/ui/Card.svelte';
	import ErrorMessage from '#lib/components/ui/ErrorMessage.svelte';
	import MetricCard from '#lib/components/ui/MetricCard.svelte';
	import Spinner from '#lib/components/ui/Spinner.svelte';
	import StatusBadge from '#lib/components/ui/StatusBadge.svelte';

	const process = asyncRead(getHealth, 'Check that FastAPI is running.');
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

	function refresh() {
		void process.refresh();
		void system.refresh();
	}
</script>

<svelte:head><title>System · Chess Coach</title></svelte:head>

<div class="flex flex-wrap items-center justify-between gap-3">
	<h1 class="text-3xl font-semibold tracking-tight">System</h1>
	<Button
		onclick={refresh}
		loading={system.state.status === 'loading' || process.state.status === 'loading'}
		>Refresh status</Button
	>
</div>

<Card>
	<h2 class="text-lg font-semibold">FastAPI process</h2>
	{#if process.state.status === 'loading'}
		<Spinner label="Checking FastAPI…" />
	{:else if process.state.status === 'error'}
		<div role="status"><StatusBadge label="Backend unavailable" tone="negative" /></div>
		<p>Start the local FastAPI service and refresh.</p>
	{:else if process.state.status === 'success'}
		<div role="status"><StatusBadge label="Backend connected" tone="positive" /></div>
	{/if}
</Card>

{#if system.state.status === 'loading'}
	<Spinner label="Loading system status…" />
{:else if system.state.status === 'error'}
	<ErrorMessage
		title="Unable to load system status."
		message={system.state.message}
		retry={refresh}
	/>
{:else if system.state.status === 'success'}
	{@const { components, statistics, status, analysis_version, checked_at } = system.state.data}
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
					{:else if service.key === 'stockfish'}
						<dd class="col-span-2 text-sm text-slate-600">
							{#if component.version}Engine: {component.version}.{/if}
							{#if component.status !== 'available'}
								Check your Stockfish installation and start the local analysis worker.{/if}
						</dd>
					{:else if service.key === 'ollama' && component.status !== 'available'}
						<dd class="col-span-2 text-sm text-slate-600">
							Start Ollama to make local coaching available.
						</dd>
					{/if}
				</div>
			{/each}
			<div class="grid grid-cols-[1fr_auto] items-center gap-2 py-3">
				<dt class="font-medium">Ollama model</dt>
				<dd>
					<StatusBadge
						label={labels[components.ollama.model_status ?? 'unknown']}
						tone={tones[components.ollama.model_status ?? 'unknown']}
					/>
				</dd>
				<dd class="col-span-2 text-sm text-slate-600">
					{components.ollama.model ?? 'Model not reported'}.
					{#if components.ollama.status === 'available' && components.ollama.model_status === 'unavailable'}
						Install the configured model in Ollama.
					{/if}
				</dd>
			</div>
		</dl>
		{#if checked_at}<p class="text-sm text-slate-600">
				Last checked: {new Date(checked_at).toLocaleString()}
			</p>{/if}
	</Card>

	{#if statistics}
		<Card>
			<h2 class="text-lg font-semibold">Local database and workflows</h2>
			<div class="grid gap-3 sm:grid-cols-3">
				<MetricCard label="Games stored" value={statistics.games_stored} />
				<MetricCard label="Games analyzed" value={statistics.games_analyzed} />
				<MetricCard label="Without completed analysis" value={statistics.pending_games} />
			</div>
			<dl class="grid gap-3 text-sm sm:grid-cols-2">
				<div>
					<dt class="font-semibold">Positions cached</dt>
					<dd>{statistics.positions_cached ?? 'Unavailable'}</dd>
				</div>
				<div>
					<dt class="font-semibold">Active sync runs</dt>
					<dd>{statistics.active_sync_runs ?? 'Unavailable'}</dd>
				</div>
				<div>
					<dt class="font-semibold">Active analysis runs</dt>
					<dd>{statistics.active_analysis_runs ?? 'Unavailable'}</dd>
				</div>
				<div>
					<dt class="font-semibold">Active coaching jobs</dt>
					<dd>{statistics.active_coaching_jobs ?? 'Unavailable'}</dd>
				</div>
				<div>
					<dt class="font-semibold">Analysis version</dt>
					<dd>{analysis_version ?? 'Unavailable'}</dd>
				</div>
			</dl>
		</Card>
	{:else}
		<p class="text-slate-600">Game counts are unavailable.</p>
	{/if}
{/if}
