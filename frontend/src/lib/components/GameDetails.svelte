<script lang="ts">
	import type { GameDetail } from '#lib/api/review.js';
	import { formatDate, results } from '#lib/utils/display.js';
	import Card from './ui/Card.svelte';
	import StatusBadge from './ui/StatusBadge.svelte';

	let { game }: { game: GameDetail } = $props();
</script>

<Card>
	<div class="flex flex-wrap items-center justify-between gap-2">
		<h2 class="min-w-0 text-xl font-semibold wrap-anywhere">
			{game.white_username} vs {game.black_username}
		</h2>
		<StatusBadge label={results[game.result]} />
	</div>
	<dl class="grid gap-3 text-sm sm:grid-cols-3">
		<div>
			<dt class="font-semibold">Played</dt>
			<dd>{formatDate(game.played_at)}</dd>
		</div>
		<div>
			<dt class="font-semibold">Your color</dt>
			<dd class="capitalize">{game.player_color}</dd>
		</div>
		<div>
			<dt class="font-semibold">Time control</dt>
			<dd class="capitalize">
				{game.time_class ?? 'Unknown'}{game.time_control ? ' · ' + game.time_control : ''}
			</dd>
		</div>
		<div>
			<dt class="font-semibold">Your rating</dt>
			<dd>
				{game.player_rating ??
					(game.player_color === 'white' ? game.white_rating : game.black_rating) ??
					'Unknown'}
			</dd>
		</div>
		<div>
			<dt class="font-semibold">White rating</dt>
			<dd>{game.white_rating ?? 'Unknown'}</dd>
		</div>
		<div>
			<dt class="font-semibold">Black rating</dt>
			<dd>{game.black_rating ?? 'Unknown'}</dd>
		</div>
		<div>
			<dt class="font-semibold">Opening</dt>
			<dd>{game.opening_name ?? game.eco_code ?? 'Unknown'}</dd>
		</div>
	</dl>
	<details>
		<summary class="cursor-pointer font-semibold">Completed game PGN</summary>
		<p class="mt-2 text-sm text-muted">
			Completion source: {game.completion_provenance === 'pgn_declaration'
				? 'declared PGN result'
				: 'Chess.com completed archive'}.
		</p>
		<pre
			class="mt-2 max-h-64 overflow-auto rounded-lg bg-raised p-3 text-sm wrap-anywhere whitespace-pre-wrap">{game.raw_pgn}</pre>
	</details>
</Card>
