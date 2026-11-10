<script lang="ts">
	import { onMount } from 'svelte';
	import { resolve } from '$app/paths';
	import { ApiError, apiErrorMessage } from '#lib/api/errors.js';
	import { isActive, jobsApi } from '#lib/api/jobs.js';
	import { watchRun } from '#lib/watch-run.svelte.js';
	import Button from '#lib/components/ui/Button.svelte';
	import Card from '#lib/components/ui/Card.svelte';
	import ErrorMessage from '#lib/components/ui/ErrorMessage.svelte';
	import Spinner from '#lib/components/ui/Spinner.svelte';
	import StatusBadge from '#lib/components/ui/StatusBadge.svelte';

	type Player = Awaited<ReturnType<typeof jobsApi.player>>;
	let player = $state<Player>(null);
	let username = $state('');
	let syncId = $state<number | null>(null);
	let analysisId = $state<number | null>(null);
	let loading = $state(true);
	let discoveryError = $state('');
	let submissionError = $state('');
	let submitting = $state<'sync' | 'analysis' | null>(null);
	const lifetime = new AbortController();

	const sync = watchRun(() => syncId, jobsApi.sync);
	const analysis = watchRun(() => analysisId, jobsApi.analysis);
	const busy = $derived(
		loading ||
			!!discoveryError ||
			!!submitting ||
			(syncId !== null &&
				(sync.state.data?.run_id !== syncId || isActive(sync.state.data.status))) ||
			(analysisId !== null &&
				(analysis.state.data?.run_id !== analysisId || isActive(analysis.state.data.status)))
	);

	async function discover() {
		loading = true;
		discoveryError = '';
		try {
			const [current, runs] = await Promise.all([
				jobsApi.player(lifetime.signal),
				jobsApi.latest(lifetime.signal)
			]);
			if (lifetime.signal.aborted) return;
			player = current;
			syncId = runs.sync_run_id;
			analysisId = runs.analysis_run_id;
		} catch (error) {
			if (!lifetime.signal.aborted)
				discoveryError = apiErrorMessage(
					error,
					'Could not check the tracked player or existing work.'
				);
		} finally {
			if (!lifetime.signal.aborted) loading = false;
		}
	}

	onMount(() => {
		void discover();
		return () => lifetime.abort();
	});

	async function submit(kind: 'sync' | 'analysis') {
		if (busy || (kind === 'analysis' && !player)) return;
		const name = (player?.username ?? username).trim();
		submissionError = '';
		if (kind === 'sync' && !/^[a-zA-Z0-9_-]{1,100}$/.test(name)) {
			submissionError =
				'Enter a Chess.com username using letters, numbers, hyphens or underscores (1–100 characters).';
			return;
		}
		submitting = kind;
		try {
			if (kind === 'sync') {
				if (!player) {
					await jobsApi.setPlayer(name, lifetime.signal);
					player = await jobsApi.player(lifetime.signal);
					// Another tab could have configured a player while this request was outstanding.
					if (player?.username !== name.toLowerCase()) {
						submissionError = 'The tracked player changed. Confirm the account before syncing.';
						return;
					}
				}
				syncId = (await jobsApi.startSync(lifetime.signal)).run_id;
			} else {
				analysisId = (await jobsApi.startAnalysis(lifetime.signal)).run_id;
			}
		} catch (error) {
			if (lifetime.signal.aborted) return;
			const conflict =
				error instanceof ApiError &&
				(error.code === 'SYNC_ALREADY_RUNNING' || error.code === 'ANALYSIS_ALREADY_RUNNING');
			submissionError = conflict
				? 'Another run already exists. Checking its status.'
				: apiErrorMessage(error, 'Could not confirm the request. Checking for an existing run.');
			await discover();
		} finally {
			if (!lifetime.signal.aborted) submitting = null;
		}
	}
</script>

<svelte:head><title>Sync · Chess Coach</title></svelte:head>

<h1 class="text-3xl font-semibold tracking-tight">Sync</h1>
<p>Import completed Chess.com games, then analyze them with local Stockfish.</p>

{#if loading}<Spinner label="Checking tracked player and existing runs…" />{/if}
{#if discoveryError}
	<ErrorMessage title="Unable to check existing work." message={discoveryError} retry={discover} />
{/if}
{#if submissionError}
	<ErrorMessage title="Sync or analysis request" message={submissionError} />
{/if}

<Card>
	<h2 class="text-lg font-semibold">Import completed games</h2>
	<form
		novalidate
		class="space-y-3"
		onsubmit={(event) => {
			event.preventDefault();
			void submit('sync');
		}}
	>
		{#if player}
			<p>Tracked Chess.com player: <strong class="wrap-anywhere">{player.username}</strong></p>
			<p class="text-sm text-muted">This library is linked to this account.</p>
		{:else}
			<label for="chesscom-username" class="block font-medium">Chess.com username</label>
			<input
				id="chesscom-username"
				class="w-full max-w-sm rounded-lg border-control-line bg-canvas text-ink focus:border-accent focus:ring-accent"
				autocomplete="off"
				autocapitalize="none"
				spellcheck={false}
				bind:value={username}
				disabled={loading || !!submitting}
			/>
			<p class="text-sm text-muted">
				{#if username.trim()}Sync will link the library to <strong class="break-all"
						>{username.trim()}</strong
					>.
				{:else}The first sync links this library to one Chess.com account.{/if}
			</p>
		{/if}
		<Button primary type="submit" disabled={busy} loading={submitting === 'sync'}>Sync Games</Button
		>
	</form>

	{#if syncId !== null}
		<p class="font-medium">Sync run #{syncId}</p>
		{#if sync.state.error}
			<p role="status">
				{sync.state.reconnecting
					? 'Connection interrupted. Reconnecting to sync status…'
					: sync.state.error}
			</p>
			{#if !sync.state.reconnecting}<Button onclick={discover}>Check latest run</Button>{/if}
		{:else if !sync.state.data}
			<Spinner label="Loading sync progress…" />
		{/if}
		{#if sync.state.data}
			{@const run = sync.state.data}
			{@const p = run.progress}
			<div role="status" class="space-y-2">
				<StatusBadge
					label={run.partial ? 'Completed with failures' : run.status}
					tone={run.status === 'failed'
						? 'caution'
						: run.status === 'completed'
							? 'positive'
							: 'neutral'}
				/>
				<p>Archives processed: {p.archives_processed} / {p.archives_total ?? 'unknown'}</p>
				<p>
					Games seen: {p.games_seen} · New games: {p.games_inserted} · Already stored: {p.games_existing}
					· Failed imports: {p.games_failed} · Unsupported: {p.games_skipped}
				</p>
				{#if p.games_quarantined}
					<p>
						{`${p.games_quarantined} ${p.games_quarantined === 1 ? 'game was' : 'games were'} skipped for analysis because PGN validation failed.`}
					</p>
				{/if}
				{#if run.status === 'queued'}<p>Waiting for the local sync worker.</p>{/if}
				{#if run.status === 'failed'}<p>
						{run.error?.message ??
							'Sync stopped. Start another sync to resume from saved archive checkpoints.'}
					</p>{/if}
			</div>
		{/if}
	{/if}
</Card>

<Card>
	<h2 class="text-lg font-semibold">Analyze imported games</h2>
	{#if !player && !loading}<p>Set your Chess.com username and import completed games first.</p>{/if}
	<Button
		primary
		onclick={() => submit('analysis')}
		disabled={busy || !player}
		loading={submitting === 'analysis'}
		>{submitting === 'analysis' ? 'Analyzing…' : 'Analyze Pending Games'}</Button
	>
	{#if analysisId !== null}
		<p class="font-medium">Analysis run #{analysisId}</p>
		{#if analysis.state.error}
			<p role="status">
				{analysis.state.reconnecting
					? 'Connection interrupted. Reconnecting to analysis status…'
					: analysis.state.error}
			</p>
			{#if !analysis.state.reconnecting}<Button onclick={discover}>Check latest run</Button>{/if}
		{:else if !analysis.state.data}
			<Spinner label="Loading analysis progress…" />
		{/if}
		{#if analysis.state.data}
			{@const run = analysis.state.data}
			<div role="status" class="space-y-2">
				<StatusBadge
					label={run.storage_status === 'completed_with_errors'
						? 'Completed with failures'
						: run.storage_status === 'cancelled'
							? 'Cancelled'
							: run.status}
					tone={run.status === 'failed'
						? 'caution'
						: run.status === 'completed'
							? 'positive'
							: 'neutral'}
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
						{run.error_message ??
							'Successful analyses are saved. Check System and retry pending games.'}
					</p>{/if}
			</div>
		{/if}
	{/if}
	<a href={resolve('/games')} class="font-medium text-accent underline">Browse games</a>
</Card>
