<script lang="ts">
	import { resolve } from '$app/paths';
	import { getGame, getGameAnalysis, type ReviewMove } from '#lib/api/review.js';
	import { asyncRead } from '#lib/async-read.svelte.js';
	import { formatDate, results } from '#lib/utils/display.js';
	import ChessBoard from './ChessBoard.svelte';
	import EvaluationChart from './EvaluationChart.svelte';
	import MoveCoaching from './MoveCoaching.svelte';
	import Button from './ui/Button.svelte';
	import Card from './ui/Card.svelte';
	import ErrorMessage from './ui/ErrorMessage.svelte';
	import Spinner from './ui/Spinner.svelte';
	import StatusBadge from './ui/StatusBadge.svelte';

	let { id, requestedPly, profile }: { id: number; requestedPly: number; profile: string | null } =
		$props();
	const game = asyncRead((signal) => getGame(id, signal), 'Could not load this game.');
	const analysis = asyncRead(
		(signal) => getGameAnalysis(id, profile, signal),
		'Could not load the stored engine evidence.'
	);
	let selection = $state<{ ply: number; before: boolean } | null>(null);
	let flipped = $state(false);

	const recorded = $derived(game.state.status === 'success' ? game.state.data : null);
	const report = $derived(analysis.state.status === 'success' ? analysis.state.data : null);
	const moves = $derived(report?.moves ?? []);
	const selected = $derived(moves.find((move) => move.ply === (selection?.ply ?? requestedPly)));
	const before = $derived(selection?.before ?? requestedPly > 0);
	const position = $derived(selected ? selected.ply - Number(before) : 0);
	const trackedColor = $derived(recorded?.player_color ?? 'white');
	const orientation = $derived(
		flipped ? (trackedColor === 'white' ? 'black' : 'white') : trackedColor
	);
	const critical = $derived(
		moves.filter((move) => move.severity === 'critical' && move.mover === trackedColor)
	);
	const profileHash = $derived(report?.profile_hash);
	const severityNames = {
		normal: 'Normal',
		minor: 'Minor error',
		significant: 'Significant error',
		critical: 'Critical error'
	};

	const notation = (move: ReviewMove) =>
		`${move.move_number}${move.mover === 'black' ? '...' : '.'} ${move.played_move_san}`;
	function evaluation(cp: number | null, mate: number | null, whiteWins: boolean | null) {
		if (mate !== null && whiteWins !== null) {
			const winner = whiteWins ? 'White' : 'Black';
			return mate === 0 ? `Checkmate · ${winner} wins` : `${winner} mates in ${Math.abs(mate)}`;
		}
		return cp === null ? 'Unavailable' : `${cp > 0 ? '+' : ''}${cp} cp`;
	}
	function show(ply: number, before = false) {
		if (ply >= 0 && ply <= moves.length) selection = { ply, before };
	}
</script>

{#if game.state.status === 'loading'}
	<Spinner label="Loading game details…" />
{:else if game.state.status === 'error'}
	<ErrorMessage title="Unable to load game." message={game.state.message} retry={game.refresh} />
{:else if recorded}
	<Card>
		<div class="flex flex-wrap items-center justify-between gap-2">
			<h2 class="min-w-0 text-xl font-semibold wrap-anywhere">
				{recorded.white_username} vs {recorded.black_username}
			</h2>
			<StatusBadge label={results[recorded.result]} />
		</div>
		<dl class="grid gap-3 text-sm sm:grid-cols-3">
			<div>
				<dt class="font-semibold">Played</dt>
				<dd>{formatDate(recorded.played_at)}</dd>
			</div>
			<div>
				<dt class="font-semibold">Your color</dt>
				<dd class="capitalize">{recorded.player_color}</dd>
			</div>
			<div>
				<dt class="font-semibold">Time control</dt>
				<dd class="capitalize">
					{recorded.time_class ?? 'Unknown'}{recorded.time_control
						? ' · ' + recorded.time_control
						: ''}
				</dd>
			</div>
			<div>
				<dt class="font-semibold">Your rating</dt>
				<dd>
					{recorded.player_rating ??
						(recorded.player_color === 'white' ? recorded.white_rating : recorded.black_rating) ??
						'Unknown'}
				</dd>
			</div>
			<div>
				<dt class="font-semibold">White rating</dt>
				<dd>{recorded.white_rating ?? 'Unknown'}</dd>
			</div>
			<div>
				<dt class="font-semibold">Black rating</dt>
				<dd>{recorded.black_rating ?? 'Unknown'}</dd>
			</div>
			<div>
				<dt class="font-semibold">Opening</dt>
				<dd>{recorded.opening_name ?? recorded.eco_code ?? 'Unknown'}</dd>
			</div>
		</dl>
		<details>
			<summary class="cursor-pointer font-semibold">Completed game PGN</summary>
			<p class="mt-2 text-sm text-muted">
				Completion source: {recorded.completion_provenance === 'pgn_declaration'
					? 'declared PGN result'
					: 'Chess.com completed archive'}.
			</p>
			<pre
				class="mt-2 max-h-64 overflow-auto rounded-lg bg-raised p-3 text-sm wrap-anywhere whitespace-pre-wrap">{recorded.raw_pgn}</pre>
		</details>
	</Card>

	{#if analysis.state.status === 'loading'}
		<Spinner label="Loading stored analysis…" />
	{:else if analysis.state.status === 'error'}
		<ErrorMessage
			title="Unable to load analysis."
			message={analysis.state.message}
			retry={analysis.refresh}
		/>
	{:else if report?.status !== 'completed'}
		<Card>
			<h2 class="text-lg font-semibold">Stored analysis</h2>
			<p>
				{report?.status === 'running'
					? 'Analysis is running.'
					: report?.status === 'failed'
						? 'Analysis failed. Successful results from other games are still saved.'
						: report?.status === 'incompatible'
							? 'The saved engine evidence is incompatible with this game or profile.'
							: 'Analysis is pending for this game.'}
			</p>
			<div class="flex flex-wrap items-center gap-3">
				<Button onclick={analysis.refresh}>Refresh analysis</Button>
				<a href={resolve('/sync')} class="font-medium text-accent underline"
					>Open Sync and analysis</a
				>
			</div>
		</Card>
	{:else if report.initial_fen !== null}
		<Card>
			<h2 class="text-lg font-semibold">Stored analysis</h2>
			<p class="text-sm text-muted">
				{report.engine_version} · {report.analysis_version} · Single pass estimates
			</p>
			{#if !selection && requestedPly > 0 && !selected}<p role="status">
					The linked ply is unavailable. Showing the starting position.
				</p>{/if}
			<div class="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,0.85fr)]">
				<section aria-label="Position viewer" class="min-w-0 space-y-3">
					<p class="font-medium" aria-live="polite">
						{selected
							? `${before ? 'Before' : 'After'} ${notation(selected)} · Ply ${selected.ply}`
							: 'Starting position'}
					</p>
					<ChessBoard
						fen={selected
							? before
								? selected.fen_before
								: selected.fen_after
							: report.initial_fen}
						{orientation}
						lastMove={before ? null : selected?.played_move_uci}
						bestMove={before ? selected?.best_move_uci : null}
					/>
					<div class="flex flex-wrap gap-2">
						<Button onclick={() => show(0)} disabled={!selected}>First position</Button>
						<Button onclick={() => show(position - 1)} disabled={position === 0}
							>Previous move</Button
						>
						<Button onclick={() => show(position + 1)} disabled={position >= moves.length}
							>Next move</Button
						>
						<Button
							onclick={() => show(moves.length)}
							disabled={!moves.length || (selected?.ply === moves.length && !before)}
							>Final position</Button
						>
						<Button
							onclick={() => {
								flipped = !flipped;
							}}>Flip board</Button
						>
						{#if selected}<Button onclick={() => show(selected.ply, !before)}
								>{before ? 'Show position after move' : 'Show position before move'}</Button
							>{/if}
					</div>
					<p class="text-sm text-muted">
						Amber marks the played move after it was made. Blue marks the engine suggestion before
						the move.
					</p>
				</section>
				<section aria-label="Move notation" class="min-w-0 space-y-3">
					<h3 class="font-semibold">Moves</h3>
					{#if moves.length}
						<ol
							class="grid max-h-72 grid-cols-2 gap-1 overflow-auto rounded-lg border border-line p-2"
						>
							{#each moves as move (move.ply)}
								<li class={move.mover === 'black' ? 'col-start-2' : 'col-start-1'}>
									<button
										type="button"
										aria-pressed={selected?.ply === move.ply}
										onclick={() => show(move.ply)}
										class="w-full rounded px-2 py-1 text-left text-sm hover:bg-raised aria-pressed:bg-positive-surface aria-pressed:font-semibold"
									>
										{notation(move)}{move.severity === 'critical' ? ' · Critical' : ''}
									</button>
								</li>
							{/each}
						</ol>
					{:else}<p>This completed game has no recorded moves.</p>{/if}
					<h3 class="font-semibold">Your critical positions</h3>
					{#if critical.length}
						<ul class="flex flex-wrap gap-2">
							{#each critical.slice(0, 8) as move (move.ply)}
								<li>
									<Button onclick={() => show(move.ply, true)}
										>{notation(move)} — Critical error</Button
									>
								</li>
							{/each}
						</ul>
					{:else}<p class="text-sm text-muted">
							No tracked-player moves were classified as critical.
						</p>{/if}
				</section>
			</div>
			<EvaluationChart {moves} />
		</Card>
		{#if selected}
			<Card>
				<h2 class="text-lg font-semibold">Move evidence · {notation(selected)}</h2>
				<dl class="grid gap-3 text-sm sm:grid-cols-2">
					<div>
						<dt class="font-semibold">Played</dt>
						<dd>
							{selected.played_move_san} ({selected.played_move_uci}) ·
							<span class="capitalize">{selected.mover}</span>
						</dd>
					</div>
					<div>
						<dt class="font-semibold">Severity</dt>
						<dd>{selected.severity ? severityNames[selected.severity] : 'Unclassified'}</dd>
					</div>
					<div>
						<dt class="font-semibold">Before move · White perspective</dt>
						<dd>
							{evaluation(
								selected.eval_before_cp_white,
								selected.mate_before_white,
								selected.mate_before_winner
							)}
						</dd>
					</div>
					<div>
						<dt class="font-semibold">After move · White perspective</dt>
						<dd>
							{evaluation(
								selected.eval_after_cp_white,
								selected.mate_after_white,
								selected.mate_after_winner
							)}
						</dd>
					</div>
					<div>
						<dt class="font-semibold">Loss for mover</dt>
						<dd>
							{selected.loss_cp === null
								? 'Not comparable in centipawns'
								: `${selected.loss_cp} cp`}
						</dd>
					</div>
					<div>
						<dt class="font-semibold">Engine best move before play</dt>
						<dd>{selected.best_move_uci ?? 'Unavailable'}</dd>
					</div>
					<div class="sm:col-span-2">
						<dt class="font-semibold">Principal variation before play</dt>
						<dd class="break-words">{selected.pv_json.join(' ') || 'Unavailable'}</dd>
					</div>
				</dl>
			</Card>
			{#if profileHash}
				{#key `${selected.ply}:${profileHash}`}
					<MoveCoaching game={id} ply={selected.ply} profile={profileHash} />
				{/key}
			{/if}
		{/if}
	{/if}
{/if}
