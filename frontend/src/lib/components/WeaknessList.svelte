<script lang="ts">
	import { resolve } from '$app/paths';
	import type { Weakness } from '#lib/api/analytics.js';
	import { weaknessLabel, words } from '#lib/utils/display.js';

	let {
		patterns,
		examples = false,
		profile = null
	}: {
		patterns: Record<string, Weakness[]>;
		examples?: boolean;
		profile?: string | null;
	} = $props();
</script>

{#if !Object.values(patterns).some((rows) => rows.length)}
	<p>Not enough analyzed games or repeated errors to identify reliable recurring weaknesses.</p>
{:else}
	{#each Object.entries(patterns) as [category, rows] (category)}
		{#if rows.length}
			<h3 class="font-semibold capitalize">{words(category)}</h3>
			<ol class="list-decimal space-y-3 pl-5">
				{#each examples ? rows : rows.slice(0, 3) as pattern (pattern.candidate_key)}
					<li>
						<p class="font-medium">{weaknessLabel(pattern.candidate_key)}</p>
						<p class="text-sm text-muted">
							{pattern.significant_errors} significant and {pattern.critical_errors} critical errors in
							{pattern.opportunities} opportunities · {pattern.distinct_games} games
						</p>
						{#if examples}
							<ul class="flex flex-wrap gap-x-4 text-sm">
								{#each pattern.source_moves.slice(0, 3) as [id, ply] (`${id}:${ply}`)}
									<li>
										<a
											href={resolve(
												`/games/[id=gameId]?ply=${ply}${profile ? '&profile=' + encodeURIComponent(profile) : ''}`,
												{ id: String(id) }
											)}
											class="text-accent underline"
										>
											Game {id}, ply {ply}
										</a>
									</li>
								{/each}
							</ul>
						{/if}
					</li>
				{/each}
			</ol>
		{/if}
	{/each}
{/if}
