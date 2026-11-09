<script lang="ts">
	let { label }: { label: string } = $props();
</script>

<p role="status" class="flex items-center gap-2 text-slate-700">
	<span
		aria-hidden="true"
		class="size-4 rounded-full border-2 border-slate-300 border-t-emerald-700 motion-safe:animate-spin"
	></span>
	{label}
</p>
