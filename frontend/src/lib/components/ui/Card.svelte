<script lang="ts">
	import type { Snippet } from 'svelte';
	let { children }: { children: Snippet } = $props();
</script>

<div class="space-y-3 rounded-xl border border-line bg-panel p-5 shadow-sm">
	{@render children()}
</div>
