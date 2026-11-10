<script lang="ts">
	import type { Overview } from '#lib/api/analytics.js';
	import { formatDate, formatRate } from '#lib/utils/display.js';

	let {
		conversion,
		conversion_strength,
		recent_trends
	}: Pick<Overview, 'conversion' | 'conversion_strength' | 'recent_trends'> = $props();
</script>

<h3 class="font-semibold">Strengths</h3>
{#if conversion_strength && conversion?.wins.per_100 != null}
	<p>
		Converted {conversion.wins.numerator} of {conversion.wins.denominator} games with a sustained engine
		advantage into wins ({formatRate(conversion.wins.per_100)}%). This is a descriptive outcome.
	</p>
{:else}
	<p>Not enough evidence to identify strengths yet.</p>
{/if}
<h3 class="font-semibold">Recent trends</h3>
{#if recent_trends.length}
	<ul class="space-y-3">
		{#each recent_trends as trend (`${trend.color}:${trend.time_class}:${trend.time_control}`)}
			<li class="rounded-lg bg-raised p-3">
				<p class="font-medium capitalize">
					{trend.color} · {trend.time_class} · Clock {trend.time_control}
				</p>
				<p class="text-sm">
					Critical errors per 100 classifiable player moves · {trend.direction} in the recent period
				</p>
				{#each [{ name: 'Earlier', period: trend.earlier }, { name: 'Recent', period: trend.recent }] as { name, period } (name)}
					<p class="text-sm">
						{name}: {period.critical.per_100 == null
							? 'Unavailable'
							: formatRate(period.critical.per_100)}
						· {period.game_ids.length} games, {period.critical.denominator} moves ·
						{formatDate(period.first_game_at)} – {formatDate(period.last_game_at)}
					</p>
				{/each}
			</li>
		{/each}
	</ul>
{:else}
	<p>Not enough analyzed games with the same color and clock control for a recent comparison.</p>
{/if}
