<script lang="ts">
	import { resolve } from '$app/paths';
	import Card from '#lib/components/ui/Card.svelte';
</script>

<svelte:head><title>Coach · Chess Coach</title></svelte:head>

<h1 class="text-3xl font-semibold tracking-tight">Coach</h1>
<Card>
	<p>Open a completed analysis and select a move to see its evidence or request an explanation.</p>
	<a
		href={resolve('/games/analysis')}
		class="font-medium text-emerald-800 underline underline-offset-4">Open analysis</a
	>
</Card>
