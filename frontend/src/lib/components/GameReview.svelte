<script lang="ts">
	import { resolve } from '$app/paths';
	import { getGame, getGameAnalysis, type ReviewMove } from '#lib/api/review.js';
	import { asyncRead } from '#lib/async-read.svelte.js';
	import { formatDate, results } from '#lib/utils/display.js';
	import BoardEvaluationBar from './BoardEvaluationBar.svelte';
	import ChessBoard from './ChessBoard.svelte';
	import EvaluationChart from './EvaluationChart.svelte';
	import MoveCoaching from './MoveCoaching.svelte';
	import ReviewMoveList from './ReviewMoveList.svelte';
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
	const scores = $derived(
		moves.length
			? [
					{
						cp: moves[0].eval_before_cp_white,
						mate: moves[0].mate_before_white,
						whiteWins: moves[0].mate_before_winner
					},
					...moves.map((move) => ({
						cp: move.eval_after_cp_white,
						mate: move.mate_after_white,
						whiteWins: move.mate_after_winner
					}))
				]
			: []
	);
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
	const engineLine = $derived(selected ?? moves[0]);
	const coachingMove = $derived(selected ?? moves[0]);
	const topColor = $derived(orientation === 'white' ? 'black' : 'white');
	const navigation = $derived([
		{ label: 'First position', icon: 'M18 5l-7 7 7 7M6 5v14', ply: 0, disabled: !selected },
		{ label: 'Previous move', icon: 'M15 5l-7 7 7 7', ply: position - 1, disabled: position === 0 },
		{
			label: 'Next move',
			icon: 'M9 5l7 7-7 7',
			ply: position + 1,
			disabled: position >= moves.length
		},
		{
			label: 'Final position',
			icon: 'M6 5l7 7-7 7m12-14v14',
			ply: moves.length,
			disabled: position >= moves.length
		}
	]);
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
	{#if report?.status !== 'completed'}
		{@render gameDetails()}
	{/if}

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
		{#if !selection && requestedPly > 0 && !selected}
			<p role="status">The linked ply is unavailable. Showing the starting position.</p>
		{/if}
		<div
			class="mx-auto grid max-w-2xl items-start gap-5 lg:max-w-[max(54rem,calc(200dvh-28rem))] lg:grid-cols-2 xl:gap-7"
		>
			<section aria-label="Position viewer" class="min-w-0 space-y-2 lg:sticky lg:top-4">
				{@render player(topColor)}
				<div
					class="grid grid-cols-[1.75rem_minmax(0,1fr)] gap-2 sm:grid-cols-[2rem_minmax(0,1fr)] sm:gap-3"
				>
					<BoardEvaluationBar score={scores[position]} {orientation} />
					<ChessBoard
						fen={selected
							? before
								? selected.fen_before
								: selected.fen_after
							: report.initial_fen}
						{orientation}
						lastMove={before ? null : selected?.played_move_uci}
						lastMoveRating={before ? undefined : selected?.rating}
						bestMove={before ? selected?.best_move_uci : null}
						review
					/>
				</div>
				{@render player(orientation)}
				<div class="mt-3 pl-9 sm:pl-11">
					{@render moveNavigation()}
				</div>
			</section>

			<aside
				aria-label="Game analysis"
				class="min-w-0 overflow-hidden rounded-xl border border-line bg-sidebar shadow-lg shadow-black/20"
			>
				<header
					class="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 bg-panel px-4 py-3"
				>
					<div>
						<h2 class="text-lg font-bold">Game Review</h2>
						<p class="text-xs text-muted" title={report.analysis_version}>
							{report.engine_version} · Single-pass analysis
						</p>
					</div>
					<Button onclick={() => (flipped = !flipped)}>Flip board</Button>
				</header>
				<div class="space-y-4 px-4 py-4">
					{#if coachingMove}
						<div class="rounded-xl bg-panel p-3">
							<div class="flex flex-wrap items-center justify-between gap-1.5">
								<p class="text-xs text-muted" aria-live="polite">
									{!selected || before ? 'Before' : 'After'}
									{notation(coachingMove)} · Ply {coachingMove.ply}
								</p>
								<button
									type="button"
									onclick={() => show(coachingMove.ply, selected ? !before : false)}
									class="rounded px-1 py-1 text-xs font-semibold underline underline-offset-2 hover:bg-raised focus-visible:outline-2"
									>{!selected || before
										? 'Show position after move'
										: 'Show position before move'}</button
								>
							</div>
						</div>
						{#if profileHash}
							{#key `${coachingMove.ply}:${profileHash}`}
								<MoveCoaching
									game={id}
									ply={coachingMove.ply}
									rating={coachingMove.rating}
									profile={profileHash}
								/>
							{/key}
						{/if}
					{/if}

					<details class="space-y-2 rounded-lg border border-line px-3 py-2">
						<summary class="cursor-pointer text-sm font-semibold">Engine best line</summary>
						<section aria-label="Engine best line" class="space-y-2">
							<div class="flex min-h-7 flex-wrap items-center justify-end gap-2">
								{#if engineLine?.best_move_uci}
									<button
										type="button"
										onclick={() => show(engineLine.ply, true)}
										aria-pressed={before && selected?.ply === engineLine.ply}
										class="rounded-md border border-positive-line bg-positive-surface px-2.5 py-1 text-xs font-semibold text-accent hover:bg-raised focus-visible:outline-2 focus-visible:outline-accent"
										>Show best move</button
									>
								{/if}
							</div>
							<div
								role="region"
								aria-label="Engine continuation"
								class="flex h-16 items-start gap-2 overflow-y-auto rounded-md bg-panel p-2.5 text-sm focus-visible:outline-2 focus-visible:outline-accent"
							>
								{#if engineLine?.pv_san}
									<span
										class="shrink-0 rounded bg-square-light px-1.5 py-0.5 text-xs font-bold text-square-ink tabular-nums"
									>
										{evaluation(
											engineLine.eval_before_cp_white,
											engineLine.mate_before_white,
											engineLine.mate_before_winner
										)}
									</span>
									<p
										class="min-w-0 font-mono leading-relaxed wrap-anywhere"
										title={engineLine.pv_json.join(' ')}
									>
										{engineLine.pv_san}
									</p>
								{:else}
									<p class="text-muted">No engine line is available for this position.</p>
								{/if}
							</div>
							<p class="min-h-4 text-xs text-muted">
								{#if engineLine?.pv_san}
									From before {notation(engineLine)} · White perspective
								{/if}
							</p>
						</section>
					</details>

					<ReviewMoveList {moves} selected={selected?.ply} onSelect={show} />
					<EvaluationChart {moves} {scores} {position} onSelect={show} />
				</div>

				<section
					aria-label="Your critical positions"
					class="space-y-2 border-t border-line px-4 py-3"
				>
					<h3 class="text-sm font-semibold">Your critical positions</h3>
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
					{:else}
						<p class="text-xs text-muted">No tracked-player moves were classified as critical.</p>
					{/if}
				</section>
			</aside>
		</div>
		{@render gameDetails()}
	{/if}
{/if}

{#snippet moveNavigation()}
	<div
		role="group"
		aria-label="Position navigation"
		class="grid grid-cols-[1fr_1.6fr_1.6fr_1fr] gap-2"
	>
		{#each navigation as control (control.label)}
			<button
				type="button"
				aria-label={control.label}
				title={control.label}
				disabled={control.disabled}
				onclick={() => show(control.ply)}
				class={[
					'grid min-h-11 place-items-center rounded-lg border border-b-4 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-45',
					control.label === 'Previous move' || control.label === 'Next move'
						? 'border-action border-b-action-edge bg-action text-action-ink enabled:hover:bg-action-hover'
						: 'border-line border-b-sidebar bg-raised text-ink enabled:hover:bg-panel'
				]}
			>
				<svg
					aria-hidden="true"
					class="size-5"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2.5"
					stroke-linecap="round"
					stroke-linejoin="round"
				>
					<path d={control.icon} />
				</svg>
			</button>
		{/each}
	</div>
{/snippet}

{#snippet player(color: 'white' | 'black')}
	{#if recorded}
		{@const name = color === 'white' ? recorded.white_username : recorded.black_username}
		{@const rating =
			(color === trackedColor ? recorded.player_rating : null) ??
			(color === 'white' ? recorded.white_rating : recorded.black_rating)}
		<div class="flex min-h-9 items-center gap-2.5 pr-0.5 pl-9 sm:pl-11">
			<span
				aria-label={color === 'white' ? 'White' : 'Black'}
				role="img"
				class={[
					'size-7 shrink-0 rounded-md border border-control-line',
					color === 'white' ? 'bg-square-light' : 'bg-neutral-900'
				]}
			></span>
			<span class="min-w-0 font-bold wrap-anywhere">{name}</span>
			{#if rating !== null}<span class="text-sm text-muted tabular-nums">({rating})</span>{/if}
			{#if color === trackedColor}
				<span
					class="ml-auto rounded-md bg-positive-surface px-2 py-0.5 text-xs font-semibold text-accent"
					>You</span
				>
			{/if}
		</div>
	{/if}
{/snippet}

{#snippet gameDetails()}
	{#if recorded}
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
	{/if}
{/snippet}
