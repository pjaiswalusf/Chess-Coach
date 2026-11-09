<script lang="ts">
	import Card from '#lib/components/ui/Card.svelte';
</script>

<svelte:head><title>Sync · Chess Coach</title></svelte:head>

<h1 class="text-3xl font-semibold tracking-tight">Sync</h1>
<Card>
	<p>Use the local Chess Coach CLI to import your completed Chess.com games.</p>
	<code class="rounded bg-slate-100 px-2 py-1 text-sm break-words"
		>uv run chess-coach sync --username YOUR_NAME</code
	>
	<p class="text-sm text-slate-600">Replace YOUR_NAME with your Chess.com username.</p>
	<h2 class="pt-2 text-lg font-semibold">Check a sync</h2>
	<p>Read local sync progress and failures with:</p>
	<code class="rounded bg-slate-100 px-2 py-1 text-sm break-words"
		>uv run chess-coach sync-status --username YOUR_NAME</code
	>
	<p class="text-sm text-slate-600">
		If the sync reports RATE_LIMITED, wait before running the import again.
	</p>
</Card>
