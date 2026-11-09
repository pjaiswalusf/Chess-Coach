<script lang="ts">
	import { resolve } from '$app/paths';
	import Card from '#lib/components/ui/Card.svelte';
</script>

<svelte:head><title>Dashboard · Chess Coach</title></svelte:head>

<h1 class="text-3xl font-semibold tracking-tight">Dashboard</h1>
<Card>
	<h2 class="text-lg font-semibold">Review your completed games</h2>
	<p class="text-slate-600">
		Browse your game history, run local analysis, or check which services are available.
	</p>
	<a href={resolve('/games')} class="font-medium text-emerald-800 underline underline-offset-4"
		>Browse games</a
	>
</Card>
