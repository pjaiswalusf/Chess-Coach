<script lang="ts">
	import { onMount } from 'svelte';
	import { analysisApi } from '#lib/api/analysis.js';
	import type { RunResponse, WorkerResponse, MoveResponse } from '#lib/api/generated.js';

	let status = $state<WorkerResponse | null>(null);
	let runs = $state<RunResponse[]>([]);
	let player = $state(0);
	let loading = $state(true);
	let submitting = $state(false);
	let error = $state('');
	let connectionError = $state('');
	let moves = $state<MoveResponse[]>([]);
	let movesLoading = $state(false);
	let selectedGame = $state<number | null>(null);
	let selection = 0;
	const active = $derived(runs.find((run) => ['pending', 'running'].includes(run.status)));

	onMount(() => {
		let disposed = false;
		let timer: ReturnType<typeof setTimeout>;
		async function refresh() {
			try {
				const [nextStatus, nextRuns] = await Promise.all([
					analysisApi.status(),
					analysisApi.runs()
				]);
				if (disposed) return;
				status = nextStatus;
				runs = nextRuns;
				if (!player) player = nextStatus.players[0]?.id ?? 0;
				connectionError = '';
			} catch (cause) {
				if (!disposed)
					connectionError = cause instanceof Error ? cause.message : 'Could not reach the API.';
			} finally {
				if (!disposed) {
					loading = false;
					timer = setTimeout(refresh, 2000);
				}
			}
		}
		void refresh();
		return () => {
			disposed = true;
			clearTimeout(timer);
		};
	});

	async function submit(cancel?: number) {
		if (submitting) return;
		submitting = true;
		try {
			const run =
				cancel === undefined ? await analysisApi.start(player) : await analysisApi.cancel(cancel);
			runs = [run, ...runs.filter((item) => item.id !== run.id)];
			error = '';
		} catch (cause) {
			error = cause instanceof Error ? cause.message : 'Request failed. Please retry.';
		} finally {
			submitting = false;
		}
	}

	async function viewGame(game: number, profile: string) {
		const current = ++selection;
		selectedGame = game;
		movesLoading = true;
		moves = [];
		try {
			const result = await analysisApi.moves(game, profile);
			if (current === selection) moves = result;
		} catch (cause) {
			if (current === selection)
				error = cause instanceof Error ? cause.message : 'Unable to load moves.';
		} finally {
			if (current === selection) movesLoading = false;
		}
	}
</script>

<svelte:head><title>Chess Coach · Analysis</title></svelte:head>

<main class="mx-auto min-h-screen max-w-5xl space-y-8 bg-white px-6 py-12 text-slate-900">
	<header class="space-y-2">
		<p class="text-sm font-semibold tracking-widest text-emerald-700 uppercase">Chess Coach</p>
		<h1 class="text-3xl font-semibold">Analyze your completed games</h1>
		<p class="text-slate-600">
			Local engine evidence from your historical games. Progress is saved as each game completes.
		</p>
	</header>

	{#if error || connectionError}<p
			role="alert"
			class="rounded-lg border border-red-300 bg-red-50 p-4"
		>
			{error || connectionError}
		</p>{/if}
	{#if loading}
		<p role="status">Loading analysis status…</p>
	{:else}
		<section aria-label="System status" class="rounded-xl border border-slate-200 p-5">
			<h2 class="mb-3 text-lg font-semibold">System</h2>
			<p>
				API: {connectionError ? 'Connection needs attention' : 'Connected'} · Database: {status?.database ??
					'Unavailable'}
			</p>
			<p>
				Worker: {status?.available ? 'Running' : 'Unavailable'} · Engine: {status?.engine_version ??
					'Not detected'}
			</p>
			{#if !status?.available}
				<p class="mt-2 text-amber-800">
					Start the local analysis worker to process games. Previously completed analyses remain
					saved.
				</p>
			{/if}
		</section>

		<form
			onsubmit={(event) => {
				event.preventDefault();
				void submit();
			}}
			class="flex flex-wrap items-end gap-4"
		>
			<label class="flex flex-col gap-2 font-medium"
				>Player
				<select
					bind:value={player}
					disabled={submitting || !!active}
					class="rounded-lg border border-slate-300 px-3 py-2"
				>
					{#each status?.players ?? [] as item (item.id)}<option value={item.id}
							>{item.username}</option
						>{/each}
				</select>
			</label>
			<button
				disabled={!player || !status?.available || submitting || !!active}
				class="rounded-lg bg-emerald-700 px-5 py-2 font-medium text-white disabled:opacity-40"
				>{submitting ? 'Submitting…' : 'Analyze eligible games'}</button
			>
		</form>
		{#if !status?.players.length}<p>
				Import and validate completed games first. No tracked players are available yet.
			</p>{/if}

		<section aria-label="Analysis runs" class="space-y-4">
			<h2 class="text-xl font-semibold">Analysis runs</h2>
			{#if !runs.length}<p class="text-slate-600">No analysis runs yet.</p>{/if}
			{#each runs as run (run.id)}
				<article class="space-y-3 rounded-xl border border-slate-200 p-5">
					<div class="flex items-center justify-between gap-4">
						<h3 class="font-semibold">Run #{run.id} · {run.status.replaceAll('_', ' ')}</h3>
						{#if ['pending', 'running'].includes(run.status)}
							<button
								onclick={() => submit(run.id)}
								disabled={submitting || run.cancel_requested}
								class="rounded-lg border border-slate-300 px-3 py-2 disabled:opacity-40"
								>{run.cancel_requested ? 'Cancellation requested' : 'Cancel run'}</button
							>
						{/if}
					</div>
					<progress
						aria-label={`Run ${run.id} progress`}
						max="100"
						value={run.progress_percent}
						class="h-3 w-full accent-emerald-700"
					></progress>
					<p>
						{run.games_completed + run.games_failed + run.games_skipped}/{run.games_total} processed ·
						{run.games_completed} completed · {run.games_skipped} already compatible · {run.games_failed}
						failed
					</p>
					<p class="text-sm text-slate-600">
						{run.games_excluded} excluded pending validation · {run.positions_analyzed} engine searches
						· {run.cache_hits} cache hits
					</p>
					<p class="text-sm text-slate-600">
						{run.engine_version} · {run.engine_config_json.nodes} nodes · Single-pass estimates
					</p>
					{#if run.last_heartbeat_at}<p class="text-sm text-slate-600">
							Last progress: {new Date(run.last_heartbeat_at).toLocaleString()}
						</p>{/if}
					{#if ['pending', 'running'].includes(run.status) && !run.worker_available}<p
							class="text-amber-800"
						>
							Worker unavailable. Restart it with the same configuration to recover unfinished work.
						</p>{/if}
					{#if run.error_code}<p class="text-amber-800">
							{run.error_code}: {run.error_message ?? 'Completed results are preserved.'}
						</p>{/if}
					{#if ['failed', 'cancelled', 'completed_with_errors'].includes(run.status)}
						<button
							onclick={() => {
								player = run.tracked_player_id;
								void submit();
							}}
							disabled={submitting || !!active || !status?.available}
							class="rounded-lg border border-emerald-700 px-3 py-2 text-emerald-800 disabled:opacity-40"
							>Retry eligible games</button
						>
					{/if}
					<details>
						<summary class="cursor-pointer">Games and evidence</summary>
						<ul class="mt-3 space-y-2">
							{#each run.games as game (game.game_id)}<li class="flex flex-wrap items-center gap-3">
									<span
										>Game #{game.game_id}: {game.status}{game.error_code
											? ` · ${game.error_code}`
											: ''}</span
									>
									{#if ['done', 'skipped'].includes(game.status)}<button
											onclick={() => viewGame(game.game_id, run.profile_hash)}
											class="text-emerald-800 underline">View moves for game {game.game_id}</button
										>{/if}
								</li>{/each}
						</ul>
					</details>
				</article>
			{/each}
		</section>
	{/if}

	{#if selectedGame !== null}
		<section aria-label="Move evidence" class="space-y-3">
			<h2 class="text-xl font-semibold">Game #{selectedGame} · Move evidence</h2>
			<p class="text-sm text-slate-600">
				Scores are from White’s perspective. Centipawn loss uses the mover’s perspective. Mate is
				separate; these are engine estimates, not confirmed mistake labels.
			</p>
			{#if movesLoading}<p role="status">Loading moves…</p>
			{:else if !moves.length}<p>No played moves in this game.</p>
			{:else}<div class="overflow-x-auto">
					<table class="w-full text-left text-sm">
						<thead
							><tr class="border-b"
								><th class="p-2">Ply</th><th class="p-2">Played</th><th class="p-2">Best (UCI)</th
								><th class="p-2">After</th><th class="p-2">Loss (cp)</th></tr
							></thead
						>
						<tbody
							>{#each moves as move (move.ply)}<tr class="border-b border-slate-100">
									<td class="p-2">{move.ply}</td><td class="p-2">{move.played_move_san}</td><td
										class="p-2">{move.best_move_uci ?? '—'}</td
									>
									<td class="p-2"
										>{move.mate_after_white !== null
											? `Mate ${move.mate_after_white} (${move.mate_after_winner ? 'White' : 'Black'})`
											: `${move.eval_after_cp_white} cp`}</td
									>
									<td class="p-2">{move.loss_cp ?? '—'}</td>
								</tr>{/each}</tbody
						>
					</table>
				</div>{/if}
		</section>
	{/if}
</main>
