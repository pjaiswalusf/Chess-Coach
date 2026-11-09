<script lang="ts">
	import { getHealth } from '#lib/api/health.js';
	import { asyncRead } from '#lib/async-read.svelte.js';
	import Button from './ui/Button.svelte';
	import StatusBadge from './ui/StatusBadge.svelte';

	const health = asyncRead(getHealth, 'Check that FastAPI is running.');
</script>

<div class="flex flex-wrap items-center gap-2">
	<div role="status">
		{#if health.state.status === 'loading'}
			<StatusBadge label="Checking backend…" />
		{:else if health.state.status === 'success'}
			<StatusBadge label="Backend connected" tone="positive" />
		{:else if health.state.status === 'error'}
			<StatusBadge label="Backend unavailable" tone="negative" />
		{/if}
	</div>
	{#if health.state.status === 'error'}
		<Button aria-label="Retry backend connection" onclick={health.refresh}>Retry</Button>
	{:else if health.state.status === 'success'}
		<Button onclick={health.refresh}>Check connection</Button>
	{/if}
</div>
