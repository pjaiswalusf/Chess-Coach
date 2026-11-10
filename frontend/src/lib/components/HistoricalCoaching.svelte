<script lang="ts">
	import { type Patterns, type Window } from '#lib/api/analytics.js';
	import { isRecord } from '#lib/api/client.js';
	import { coachingApi, getLLMHealth } from '#lib/api/coaching.js';
	import { asyncRead } from '#lib/async-read.svelte.js';
	import { coachingJob } from '#lib/coaching-job.svelte.js';
	import { weaknessLabel } from '#lib/utils/display.js';
	import Button from './ui/Button.svelte';
	import Card from './ui/Card.svelte';
	import Spinner from './ui/Spinner.svelte';

	let {
		window,
		profile,
		report,
		refresh
	}: {
		window: Window;
		profile: string;
		report: Patterns;
		refresh: () => void;
	} = $props();

	const job = coachingJob(
		(signal) => coachingApi.history(window, profile, signal),
		(signal) => coachingApi.history(window, profile, signal, report.report_hash ?? undefined)
	);
	const health = asyncRead(getLLMHealth, 'Could not check the local coaching model.');
	const result = $derived(job.result);
	const interpretations = $derived(
		result?.coach && 'priorities' in result.coach ? result.coach : null
	);
	const model = $derived(health.state.status === 'success' ? health.state.data : null);
	const stale = $derived(
		Boolean(
			result &&
			(!isRecord(result.evidence) ||
				!('report_hash' in result.evidence) ||
				!report.report_hash ||
				result.evidence.report_hash !== report.report_hash)
		)
	);
	const readable = $derived(
		interpretations &&
			Array.isArray(interpretations.priorities) &&
			interpretations.priorities.every(
				(item) =>
					isRecord(item) &&
					typeof item.pattern_id === 'string' &&
					typeof item.explanation === 'string' &&
					typeof item.practice_tip === 'string'
			)
	);
</script>

<Card>
	<h2 class="text-lg font-semibold">Coach interpretation and practice</h2>
	<p class="text-sm text-muted">Local model advice based on the measured evidence above.</p>
	{#if job.loading}
		<Spinner label="Loading saved historical coaching…" />
	{:else if stale}
		<p role="status">
			The coaching evidence and measured report differ. Refresh the report before using this
			interpretation.
		</p>
		<Button onclick={refresh}>Refresh measured evidence</Button>
	{:else}
		{#if job.error}
			<p role="alert">Coaching explanation unavailable. {job.error}</p>
		{:else if result?.status === 'done' && interpretations && readable}
			<p>{interpretations.summary}</p>
			<ul class="space-y-3">
				{#each interpretations.priorities as item (item.pattern_id)}
					<li>
						<p class="font-semibold">{weaknessLabel(item.pattern_id)}</p>
						<p>{item.explanation}</p>
						<p><strong>Suggested practice:</strong> {item.practice_tip}</p>
					</li>
				{/each}
			</ul>
		{:else if result?.status === 'done'}
			<p role="alert">The saved explanation could not be displayed.</p>
		{:else if result?.status === 'insufficient_evidence'}
			<p>{interpretations?.summary ?? 'There is insufficient evidence for reliable coaching.'}</p>
		{:else if job.active}
			<p role="status">Historical coaching is {result?.status}. {result?.message ?? ''}</p>
		{:else if result?.status === 'failed'}
			<p role="alert">
				Coaching explanation unavailable. {result.message ?? 'Check Ollama and retry.'}
			</p>
		{:else if model && model.status !== 'ready'}
			<p role="status">
				Coaching explanation unavailable. {model.status === 'model_missing'
					? `Install ${model.model} in Ollama.`
					: 'Check that Ollama is running.'} Stockfish analysis and statistics are still available.
			</p>
		{:else}
			<p>No saved explanation for this window.</p>
		{/if}

		{#if job.statusError}
			<Button onclick={job.refresh}>Refresh coaching status</Button>
		{:else if !job.active && result?.status !== 'done' && result?.status !== 'insufficient_evidence'}
			<Button primary onclick={job.submit} loading={job.submitting}
				>Generate historical coaching</Button
			>
		{/if}
	{/if}
</Card>
