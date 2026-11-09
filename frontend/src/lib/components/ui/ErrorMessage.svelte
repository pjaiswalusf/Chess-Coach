<script lang="ts">
	import Button from './Button.svelte';
	let { title, message, retry }: { title: string; message: string; retry?: () => void } = $props();
</script>

<div class="space-y-3 rounded-lg border border-red-200 bg-red-50 p-4 text-red-900">
	<div role="alert">
		<p class="font-semibold">{title}</p>
		<p>{message}</p>
	</div>
	{#if retry}<Button onclick={retry}>Retry</Button>{/if}
</div>
