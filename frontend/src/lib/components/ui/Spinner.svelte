<script lang="ts">
	let { label }: { label: string } = $props();
</script>

<p role="status" class="flex items-center gap-2 text-muted">
	<span
		aria-hidden="true"
		class="size-4 rounded-full border-2 border-control-line border-t-accent motion-safe:animate-spin"
	></span>
	{label}
</p>
