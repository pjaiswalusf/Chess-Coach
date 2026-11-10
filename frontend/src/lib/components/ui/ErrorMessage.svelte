<script lang="ts">
	import Button from './Button.svelte';
	let { title, message, retry }: { title: string; message: string; retry?: () => void } = $props();
</script>

<div class="space-y-3 rounded-lg border border-danger-line bg-danger-surface p-4 text-danger">
	<div role="alert">
		<p class="font-semibold">{title}</p>
		<p>{message}</p>
	</div>
	{#if retry}<Button onclick={retry}>Retry</Button>{/if}
</div>
