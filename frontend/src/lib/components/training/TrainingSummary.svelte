<script lang="ts">
	import type { TrainingStats, TransferReport } from '#lib/api/training.js';
	import Card from '#lib/components/ui/Card.svelte';
	import MetricCard from '#lib/components/ui/MetricCard.svelte';
	import { resolve } from '$app/paths';
	import { formatDate, formatRate, words } from '#lib/utils/display.js';

	let { stats, progress }: { stats: TrainingStats; progress?: TransferReport } = $props();
	const accuracy = (value: number | null) =>
		value == null ? 'Not yet measured' : formatRate(100 * value) + '%';
</script>

<Card>
	<h2 class="text-lg font-semibold">Puzzle activity</h2>
	<div class="grid gap-3 sm:grid-cols-3">
		<MetricCard
			label="Puzzles practiced"
			value={stats.puzzles_attempted + ' / ' + stats.puzzles_total}
		/>
		<MetricCard label="Answer accuracy" value={accuracy(stats.accuracy)} />
		<MetricCard label="Due now" value={stats.puzzles_due} />
	</div>
	<p class="text-sm text-muted">
		{stats.attempts_total} attempt{stats.attempts_total === 1 ? '' : 's'} · {stats.correct_attempts} correct
		· {stats.incorrect_attempts} incorrect
		{#if stats.average_attempts !== null}
			· {formatRate(stats.average_attempts)} attempt{stats.average_attempts === 1 ? '' : 's'} per practiced
			puzzle
		{/if}
	</p>
	{#if stats.themes.length}
		<h3 class="font-semibold">By theme</h3>
		<ul class="space-y-2 text-sm">
			{#each stats.themes as theme (theme.theme)}
				<li class="flex flex-wrap justify-between gap-2">
					<span class="capitalize">{words(theme.theme)}</span>
					<span
						>{accuracy(theme.accuracy)} · {theme.correct}/{theme.attempts} correct · {theme.puzzles} puzzle{theme.puzzles ===
						1
							? ''
							: 's'}</span
					>
				</li>
			{/each}
		</ul>
	{/if}
</Card>

{#if progress}
	<Card>
		<h2 class="text-lg font-semibold">Performance in completed games</h2>
		{#if !progress.first_attempt_at}
			<p class="text-sm">Complete a puzzle to start the before-and-after comparison.</p>
		{:else}
			<p class="text-sm">
				Training began {formatDate(progress.first_attempt_at)}. Rates count moves with a loss of
				{progress.critical_loss_cp} centipawns or more per 100 tracked-player moves scored in centipawns.
				Comparisons require at least {progress.min_games_per_period} games and
				{progress.min_moves_per_period} such moves in each period.
			</p>
			{#if !progress.cohorts.some((cohort) => cohort.change_per_100 != null)}
				<p class="text-sm">
					Comparable games and scored moves are still below the comparison threshold.
				</p>
			{/if}
			{#each progress.cohorts as cohort (`${cohort.time_class}/${cohort.time_control}/${cohort.color}/${cohort.profile_hash}/${cohort.analysis_version}`)}
				<details class="rounded-lg border border-line p-3 text-sm">
					<summary class="cursor-pointer font-semibold">
						<span class="capitalize">{cohort.time_class} · {cohort.color}</span> · {cohort.time_control}
						{#if cohort.change_per_100 != null}
							· {formatRate(cohort.change_per_100)} observed change per 100 moves
							{#if cohort.relative_change_percent != null}
								({formatRate(cohort.relative_change_percent)}%)
							{/if}
						{/if}
					</summary>
					<p class="mt-2">
						Analysis {cohort.analysis_version} · profile {cohort.profile_hash.slice(0, 12)}
					</p>
					{#each [{ name: 'Before', evidence: cohort.before }, { name: 'After', evidence: cohort.after }] as period (period.name)}
						<div class="mt-2">
							<p>
								<strong>{period.name}</strong> · {period.evidence.game_ids.length} games ·
								{period.evidence.moves} moves · {period.evidence.critical_errors} critical errors
								{#if period.evidence.errors_per_100 != null}
									· {formatRate(period.evidence.errors_per_100)} errors per 100 moves
								{/if}
							</p>
							<div class="flex flex-wrap gap-x-2">
								{#each period.evidence.game_ids as id (id)}
									<a
										class="text-accent underline"
										href={resolve(
											`/games/[id=gameId]?profile=${encodeURIComponent(cohort.profile_hash)}`,
											{ id: String(id) }
										)}>Game {id}</a
									>
								{/each}
							</div>
						</div>
					{/each}
				</details>
			{/each}
		{/if}
	</Card>
{/if}
