<script lang="ts">
	import Card from './Card.svelte';
	let { label, value }: { label: string; value: number | string } = $props();
</script>

<Card>
	<dl>
		<dt class="text-sm font-medium text-slate-600">{label}</dt>
		<dd class="text-2xl font-semibold tabular-nums">{value}</dd>
	</dl>
</Card>
