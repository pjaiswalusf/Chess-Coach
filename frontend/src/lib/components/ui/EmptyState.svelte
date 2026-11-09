<script lang="ts">
	import type { Snippet } from 'svelte';
	import Card from './Card.svelte';
	let { title, children }: { title: string; children: Snippet } = $props();
</script>

<Card>
	<h2 class="text-lg font-semibold">{title}</h2>
	{@render children()}
</Card>
