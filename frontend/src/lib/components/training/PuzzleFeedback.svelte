<script lang="ts">
	import type { AttemptResult } from '#lib/api/training.js';
	import { resolve } from '$app/paths';
	import { formatDate } from '#lib/utils/display.js';

	let { result }: { result: AttemptResult } = $props();
</script>

<div role="status" class="space-y-2 rounded-lg border border-line bg-canvas p-4">
	<p class={['font-semibold', result.correct ? 'text-accent' : 'text-warning']}>
		{result.correct ? 'Correct' : 'Incorrect'}
	</p>
	<p>Engine solution <strong>{result.solution_san}</strong></p>
	<p class="text-sm">Verified line {result.solution_pv_san.join(' ')}</p>
	<p class="text-sm">Next review {formatDate(result.next_review_at)}</p>
	<a
		class="inline-block text-sm font-semibold text-accent underline"
		href={resolve(
			`/games/[id=gameId]?ply=${result.source_ply}&profile=${encodeURIComponent(result.source_profile_hash)}`,
			{ id: String(result.source_game_id) }
		)}>Review source game, ply {result.source_ply}</a
	>
</div>
