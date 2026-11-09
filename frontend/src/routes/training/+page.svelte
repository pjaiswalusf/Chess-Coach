<script lang="ts">
	import { resolve } from '$app/paths';
	import { ApiError, apiErrorMessage } from '#lib/api/errors.js';
	import {
		getNextPuzzle,
		getTrainingProgress,
		getTrainingStats,
		submitPuzzleAttempt,
		type AttemptResult,
		type SubmitAttempt
	} from '#lib/api/training.js';
	import { asyncRead } from '#lib/async-read.svelte.js';
	import PuzzleBoard from '#lib/components/training/PuzzleBoard.svelte';
	import PuzzleFeedback from '#lib/components/training/PuzzleFeedback.svelte';
	import TrainingSummary from '#lib/components/training/TrainingSummary.svelte';
	import Button from '#lib/components/ui/Button.svelte';
	import Card from '#lib/components/ui/Card.svelte';
	import ErrorMessage from '#lib/components/ui/ErrorMessage.svelte';
	import Spinner from '#lib/components/ui/Spinner.svelte';
	import { words } from '#lib/utils/display.js';

	const queue = asyncRead(getNextPuzzle, 'Check the local backend and retry.');
	const stats = asyncRead(getTrainingStats, 'Check the local backend and retry.');
	const progress = asyncRead(getTrainingProgress, 'Check the local backend and retry.');

	let move = $state<string | null>(null);
	let pending = $state<SubmitAttempt | null>(null);
	let result = $state<AttemptResult | null>(null);
	let busy = $state(false);
	let problem = $state('');
	let stale = $state(false);

	async function submit(id: number) {
		if (!move || busy || result || stale) return;
		pending ??= { submission_id: crypto.randomUUID(), move_uci: move };
		busy = true;
		problem = '';
		try {
			result = await submitPuzzleAttempt(id, pending);
			pending = null;
			void stats.refresh();
			void progress.refresh();
		} catch (error) {
			problem = apiErrorMessage(error, 'Unable to submit your move.');
			if (error instanceof ApiError) {
				if (error.status === 422) pending = null;
				if (error.status === 409 || error.status === 404) stale = true;
			}
		} finally {
			busy = false;
		}
	}

	function next() {
		move = null;
		pending = null;
		result = null;
		problem = '';
		stale = false;
		void queue.refresh();
	}
</script>

<svelte:head><title>Training · Chess Coach</title></svelte:head>

<h1 class="text-3xl font-semibold tracking-tight">Training</h1>
<p class="text-slate-700">
	Practice finding the best first move in positions from your completed games.
</p>

<Card>
	{#if queue.state.status === 'loading'}
		<Spinner label="Loading your next puzzle…" />
	{:else if queue.state.status === 'error'}
		<ErrorMessage title="Could not load training." message={queue.state.message} retry={next} />
	{:else if queue.state.status === 'success' && queue.state.data.puzzle}
		{@const puzzle = queue.state.data.puzzle}
		<h2 class="text-lg font-semibold capitalize">{puzzle.side_to_move} to move</h2>
		<p class="text-sm text-slate-700 capitalize">
			{words(puzzle.theme)} · {puzzle.difficulty} · {puzzle.attempt_count ? 'Review' : 'New puzzle'}
		</p>
		{#key puzzle.id}
			<PuzzleBoard
				{puzzle}
				disabled={busy || !!pending || !!result}
				solution={result?.solution_move_uci}
				onMove={(choice) => {
					move = choice;
					problem = '';
				}}
			/>
		{/key}
		{#if result}
			<PuzzleFeedback {result} />
			<Button onclick={next}>Next puzzle</Button>
		{:else}
			{#if problem}
				<ErrorMessage title="Move submission failed." message={problem} />
			{/if}
			{#if stale}
				<Button onclick={next}>Load current puzzle</Button>
			{:else}
				<Button disabled={!move} loading={busy} onclick={() => void submit(puzzle.id)}>
					{busy ? 'Submitting…' : pending ? 'Retry submission' : 'Submit move'}
				</Button>
			{/if}
		{/if}
	{:else}
		<h2 class="text-lg font-semibold">All caught up</h2>
		<p>No puzzles are due right now.</p>
		<div class="flex flex-wrap items-center gap-3">
			<Button onclick={next}>Refresh queue</Button>
			<a class="text-sm font-semibold text-emerald-800 underline" href={resolve('/system')}
				>View training status</a
			>
		</div>
	{/if}
</Card>

{#if stats.state.status === 'loading'}
	<Spinner label="Loading puzzle activity…" />
{:else if stats.state.status === 'error'}
	<ErrorMessage
		title="Could not load puzzle activity."
		message={stats.state.message}
		retry={stats.refresh}
	/>
{:else if stats.state.status === 'success'}
	<TrainingSummary
		stats={stats.state.data}
		progress={progress.state.status === 'success' ? progress.state.data : undefined}
	/>
{/if}
{#if progress.state.status === 'loading'}
	<Spinner label="Loading completed-game comparison…" />
{:else if progress.state.status === 'error'}
	<ErrorMessage
		title="Could not load completed-game comparison."
		message={progress.state.message}
		retry={progress.refresh}
	/>
{/if}
