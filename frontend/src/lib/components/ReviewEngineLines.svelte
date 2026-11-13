<script lang="ts">
	import type { ReviewEngineLine } from '#lib/api/review.js';
	import { evaluationLabel } from '#lib/utils/display.js';
	import ChessNotation from './ChessNotation.svelte';

	let {
		lines,
		loading,
		legacyBackend,
		error,
		legal,
		disabled,
		onPlay,
		onRetry
	}: {
		lines: ReviewEngineLine[];
		loading: boolean;
		legacyBackend: boolean;
		error: string | undefined;
		legal: string[];
		disabled: boolean;
		onPlay: (move: string) => void;
		onRetry: () => void;
	} = $props();

	function label(line: ReviewEngineLine) {
		if (line.mate !== null) return `${line.white_wins ? '+' : '−'}M${Math.abs(line.mate)}`;
		return evaluationLabel(line.cp, line.mate, line.white_wins);
	}
</script>

<section aria-label="Engine lines" class="min-w-0 space-y-1">
	<div class="flex items-baseline gap-2 text-xs text-muted">
		<h3 class="font-semibold">Engine lines</h3>
		{#if loading}<span role="status">Analyzing…</span>{/if}
	</div>
	<ol class="list-none space-y-1">
		{#each lines as line, index (line.continuation)}
			<li
				class="grid min-w-0 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2 rounded-md bg-panel px-2 py-1 text-xs"
			>
				<span
					class="min-w-9 rounded-sm bg-square-light px-1 text-center font-bold text-square-ink tabular-nums"
					title={`${evaluationLabel(line.cp, line.mate, line.white_wins)} (White perspective)`}
					>{label(line)}</span
				>
				<!-- svelte-ignore a11y_no_noninteractive_tabindex (The continuation scrolls horizontally with the keyboard.) -->
				<div
					role="group"
					aria-label={index === 0 ? 'Best continuation' : 'Second continuation'}
					tabindex="0"
					class="min-w-0 [scrollbar-width:none] overflow-x-auto font-mono leading-5 whitespace-nowrap focus-visible:outline-1 focus-visible:outline-accent"
					title={line.continuation}
				>
					<ChessNotation text={line.continuation} variation />
				</div>
				{#if line.best_move && legal.includes(line.best_move)}
					<button
						type="button"
						aria-label={index === 0 ? 'Play best move' : 'Play second engine move'}
						title={index === 0 ? 'Play best move' : 'Play second engine move'}
						class="rounded-sm px-1.5 py-0.5 text-accent focus-visible:outline-1 enabled:hover:bg-raised disabled:opacity-50"
						{disabled}
						onclick={() => line.best_move && onPlay(line.best_move)}>▶</button
					>
				{/if}
			</li>
		{/each}
	</ol>
	{#if error}
		<div class="flex flex-wrap items-center gap-x-2 text-xs text-muted">
			<p role="status">{error}</p>
			<button type="button" class="font-semibold text-accent underline" onclick={onRetry}
				>Retry</button
			>
		</div>
	{:else if legacyBackend}
		<p role="status" class="text-xs text-muted">Restart Chess Coach to load both engine lines.</p>
	{:else if !loading && !lines.length}
		<p class="text-xs text-muted">No engine continuations.</p>
	{/if}
</section>
