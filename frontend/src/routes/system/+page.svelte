<script lang="ts">
	import { getHealth } from '#lib/api/health.js';
	import { getComponentHealth, getSystemMetrics } from '#lib/api/system.js';
	import { asyncRead } from '#lib/async-read.svelte.js';
	import Button from '#lib/components/ui/Button.svelte';
	import Card from '#lib/components/ui/Card.svelte';
	import ErrorMessage from '#lib/components/ui/ErrorMessage.svelte';
	import MetricCard from '#lib/components/ui/MetricCard.svelte';
	import Spinner from '#lib/components/ui/Spinner.svelte';
	import StatusBadge from '#lib/components/ui/StatusBadge.svelte';

	const process = asyncRead(getHealth, 'Check that FastAPI is running.');
	const system = asyncRead(getComponentHealth, 'Check the local backend and retry.');
	const metrics = asyncRead(getSystemMetrics, 'Check the local database and retry.');
	const serviceLabels: Record<string, string> = {
		configuration: 'Configuration',
		data_directory: 'Data directory',
		database: 'Database',
		migrations: 'Database migrations',
		stockfish: 'Stockfish',
		ollama: 'Ollama',
		ollama_model: 'Ollama model'
	};
	const labels = {
		pass: 'Available',
		warn: 'Warning',
		fail: 'Unavailable',
		skip: 'Unknown'
	} as const;
	const tones = { pass: 'positive', warn: 'caution', fail: 'negative', skip: 'caution' } as const;
	const format = (value: number | null | undefined, unit: string) =>
		value == null
			? 'Unavailable'
			: value.toLocaleString(undefined, { maximumFractionDigits: 1 }) + unit;

	function refresh() {
		void process.refresh();
		void system.refresh();
		void metrics.refresh();
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
	{@const {
		components,
		overall: status,
		checked_at,
		statistics,
		analysis_version,
		training,
		engine_version,
		model
	} = system.state.data}
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
		<dl class="divide-y divide-line">
			{#each Object.entries(components) as [name, check] (name)}
				<div class="grid grid-cols-[1fr_auto] items-center gap-2 py-3">
					<dt class="font-medium">{serviceLabels[name] ?? name}</dt>
					<dd><StatusBadge label={labels[check.status]} tone={tones[check.status]} /></dd>
					<dd class="col-span-2 text-sm text-muted">
						{check.message}
						{#if name === 'stockfish' && engine_version}{engine_version}.{/if}
						{#if name === 'ollama_model' && model}Configured model {model}.{/if}
					</dd>
					{#if check.action}
						<dd class="col-span-2 text-sm text-muted">{check.action}</dd>
					{/if}
				</div>
			{/each}
		</dl>
		{#if status !== 'unavailable'}
			<p class="text-sm text-muted">Stored games and historical analysis are available.</p>
			{#if components.stockfish?.status === 'warn'}
				<p class="text-sm text-muted">New engine analysis is unavailable.</p>
			{:else if components.stockfish?.status === 'pass'}
				<p class="text-sm text-muted">New analysis requires a running local analysis worker.</p>
			{/if}
			{#if components.ollama_model?.status !== 'pass'}
				<p class="text-sm text-muted">New AI explanations are unavailable.</p>
			{/if}
		{/if}
		<p class="text-sm text-muted">
			Last checked {new Date(checked_at).toLocaleString()}
		</p>
	</Card>

	{#if training}
		<Card>
			<h2 class="text-lg font-semibold">Training status</h2>
			<p>Practice {training.practice_status === 'ready' ? 'ready' : 'unavailable'}.</p>
			{#if training.puzzles_total != null}
				<p class="text-sm">{training.puzzles_total} stored puzzles · {training.puzzles_due} due</p>
			{/if}
			<p class="text-sm">{training.detail}</p>
		</Card>
	{/if}

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
		<p class="text-muted">Game counts are unavailable.</p>
	{/if}
{/if}

<Card>
	<h2 class="text-lg font-semibold">Performance metrics</h2>
	{#if metrics.state.status === 'loading'}
		<Spinner label="Loading performance metrics…" />
	{:else if metrics.state.status === 'error'}
		<ErrorMessage
			title="Metrics unavailable."
			message={metrics.state.message}
			retry={metrics.refresh}
		/>
	{:else if metrics.state.status === 'success'}
		{@const { analysis, coaching } = metrics.state.data}
		<p class="text-sm text-muted">
			{analysis ? 'Latest finished analysis run #' + analysis.run_id : 'No finished analysis runs.'}
		</p>
		<div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
			<MetricCard
				label="Engine throughput"
				value={format(analysis?.positions_per_second, ' positions/s')}
			/>
			<MetricCard label="Cache hit rate" value={format(analysis?.cache_hit_rate, '%')} />
			<MetricCard
				label="Active analysis time"
				value={format(analysis?.duration_ms == null ? null : analysis.duration_ms / 1000, ' s')}
			/>
			<MetricCard label="Games per hour" value={format(analysis?.games_per_hour, '')} />
		</div>
		<p class="text-sm text-muted">
			Coaching over {coaching.window_days} days · {coaching.sample_count} measured jobs ·
			{coaching.first_schema_sample_count} classified first responses
		</p>
		<div class="grid gap-3 sm:grid-cols-3">
			<MetricCard
				label="LLM latency p50"
				value={format(
					coaching.latency_p50_ms == null ? null : coaching.latency_p50_ms / 1000,
					' s'
				)}
			/>
			<MetricCard
				label="First-response schema failure rate"
				value={format(coaching.first_schema_failure_rate, '%')}
			/>
			<MetricCard label="Final LLM failure rate" value={format(coaching.final_failure_rate, '%')} />
		</div>
	{/if}
</Card>
