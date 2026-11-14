<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { ApiError, apiErrorMessage } from '#lib/api/errors.js';
	import {
		getNextPuzzle,
		getTrainingProgress,
		getTrainingStats,
		playPuzzle,
		submitPuzzleAttempt,
		type AttemptResult,
		type PublicPuzzle
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

	const target = $derived(page.url.searchParams.get('puzzle') ?? undefined);
	const queue = asyncRead(
		(signal) => getNextPuzzle(signal, target),
		'Check the local backend and retry.',
		undefined,
		() => target
	);
	const stats = asyncRead(getTrainingStats, 'Check the local backend and retry.');
	const progress = asyncRead(getTrainingProgress, 'Check the local backend and retry.');

	let pending = $state<{
		submission_id: string;
		moves: string[];
		retry_after_attempt_id?: number;
	} | null>(null);
	let retryAttempt = $state<number | undefined>(undefined);
	let boardVersion = $state(0);
	let solveStreak = $state<number | undefined>(undefined);
	let played = $state<string[]>([]);
	let position = $state<Pick<PublicPuzzle, 'fen' | 'legal_moves'> | null>(null);
	let reply = $state('');
	let result = $state<AttemptResult | null>(null);
	let busy = $state(false);
	let problem = $state('');
	let stale = $state(false);
	$effect(() => {
		if (stats.state.status === 'success') solveStreak = stats.state.data.solve_streak ?? 0;
	});

	async function submit(puzzle: PublicPuzzle, move?: string) {
		if (busy || result || stale || (!pending && !move)) return;
		if (move && !pending)
			pending = {
				submission_id: crypto.randomUUID(),
				moves: [...played, move],
				...(retryAttempt ? { retry_after_attempt_id: retryAttempt } : {})
			};
		const request = pending;
		if (!request) return;
		busy = true;
		problem = '';
		try {
			if ((puzzle.solver_moves ?? 1) > 1) {
				const step = await playPuzzle(puzzle.id, request);
				if (step.continuation) {
					position = step.continuation;
					reply = step.continuation.reply_san;
					played = request.moves;
				}
				result = step.result ?? null;
			} else {
				result = await submitPuzzleAttempt(puzzle.id, {
					submission_id: request.submission_id,
					move_uci: request.moves[0],
					...(retryAttempt ? { retry_after_attempt_id: retryAttempt } : {})
				});
			}
			pending = null;
			if (result) {
				solveStreak = result.correct ? (solveStreak ?? 0) + 1 : 0;
				void stats.refresh();
				void progress.refresh();
			}
		} catch (error) {
			problem = apiErrorMessage(error, 'Unable to submit your move.');
			if (error instanceof ApiError) {
				if (error.status === 422) {
					pending = null;
					boardVersion++;
				}
				if (error.status === 409 || error.status === 404) stale = true;
			}
		} finally {
			busy = false;
		}
	}

	function retryPuzzle() {
		if (!result || result.correct) return;
		retryAttempt = result.attempt_id;
		result = null;
		problem = '';
		boardVersion++;
	}

	function reset() {
		retryAttempt = undefined;
		pending = null;
		result = null;
		played = [];
		position = null;
		reply = '';
		problem = '';
		stale = false;
	}

	$effect(() => {
		void target;
		reset();
	});

	function next() {
		reset();
		if (target) void goto(resolve('/training'));
		else void queue.refresh();
	}
</script>

<svelte:head><title>Puzzles · Chess Coach</title></svelte:head>

<h1 class="text-3xl font-semibold tracking-tight">Puzzles</h1>
<p class="text-muted">Solve tactics from your completed games.</p>
<p role="status" class="font-semibold">
	{solveStreak ?? 0} solved in a row
</p>

<Card>
	{#if queue.state.status === 'loading'}
		<Spinner label="Loading your next puzzle…" />
	{:else if queue.state.status === 'error'}
		<ErrorMessage
			title="Could not load puzzles."
			message={queue.state.message}
			retry={queue.refresh}
		/>
	{:else if queue.state.status === 'success' && queue.state.data.puzzle}
		{@const puzzle = queue.state.data.puzzle}
		<h2 class="text-lg font-semibold capitalize">{puzzle.side_to_move} to move</h2>
		<p class="text-sm text-muted capitalize">
			{words(puzzle.theme)} · {puzzle.difficulty} · {puzzle.attempt_count ? 'Review' : 'New puzzle'}
		</p>
		{#if (puzzle.solver_moves ?? 1) > 1 && !result}
			<p role="status" class="text-sm">
				{#if reply}Correct. Opponent played {reply}.{/if}
				Move {played.length + 1} of {puzzle.solver_moves}
			</p>
		{/if}
		{#key `${puzzle.id}:${played.length}:${!!result}:${boardVersion}`}
			<PuzzleBoard
				puzzle={result?.final_fen
					? { ...puzzle, fen: result.final_fen, legal_moves: [] }
					: result || !position
						? puzzle
						: { ...puzzle, ...position }}
				disabled={busy || !!pending || !!result}
				solution={result?.final_fen ? undefined : result?.solution_move_uci}
				lastMove={result?.last_move_uci ?? undefined}
				onMove={(choice) => {
					if (choice && !pending) void submit(puzzle, choice);
				}}
			/>
		{/key}
		{#if result}
			<PuzzleFeedback {result} />
			{#if !result.correct}<Button primary onclick={retryPuzzle}>Retry puzzle</Button>{/if}
			<Button primary={result.correct} onclick={next}>Next puzzle</Button>
		{:else}
			{#if problem}
				<ErrorMessage title="Move submission failed." message={problem} />
			{/if}
			{#if stale}
				<Button onclick={next}>Load current puzzle</Button>
			{:else if busy}
				<Spinner label="Checking move…" />
			{:else if pending}
				<Button primary onclick={() => void submit(puzzle)}>Retry submission</Button>
			{/if}
		{/if}
	{:else}
		<h2 class="text-lg font-semibold">
			{target ? 'This practice puzzle is unavailable' : 'All caught up'}
		</h2>
		<p>{target ? 'Continue with the regular puzzle queue.' : 'No puzzles are due right now.'}</p>
		<div class="flex flex-wrap items-center gap-3">
			<Button onclick={next}>{target ? 'Open puzzle queue' : 'Refresh queue'}</Button>
			<a class="text-sm font-semibold text-accent underline" href={resolve('/system')}
				>View puzzle status</a
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
