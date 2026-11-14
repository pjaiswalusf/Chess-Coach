<script lang="ts">
	import { isActive, type AnalysisProgress } from '#lib/api/jobs.js';
	import StatusBadge from '#lib/components/ui/StatusBadge.svelte';

	let { run }: { run: AnalysisProgress } = $props();
</script>

<div role="status" class="space-y-2">
	<StatusBadge
		label={run.storage_status === 'completed_with_errors'
			? 'Completed with failures'
			: run.storage_status === 'cancelled'
				? 'Cancelled'
				: run.status}
		tone={run.status === 'failed' ? 'caution' : run.status === 'completed' ? 'positive' : 'neutral'}
	/>
	{#if run.status === 'completed' && run.games_total === run.games_skipped}
		<p>No pending games were eligible for analysis.</p>
		{#if run.games_skipped}<p>Already analyzed: {run.games_skipped}</p>{/if}
	{:else}
		<p>
			Games selected: {run.games_total} · Analyzed: {run.games_completed} · Failed: {run.games_failed}
			· Already analyzed: {run.games_skipped} · Remaining: {run.games_remaining}
		</p>
	{/if}
	{#if run.games_excluded}<p>
			Excluded games without compatible parsed source: {run.games_excluded}.
		</p>{/if}
	{#if isActive(run.status) && !run.worker_available}<p>
			Waiting for the local analysis worker to resume.
		</p>{/if}
	{#if run.status === 'failed'}<p>
			{run.error_message ?? 'Successful analyses are saved. Check System and retry pending games.'}
		</p>{/if}
</div>
