<script lang="ts">
	import type { HTMLButtonAttributes } from 'svelte/elements';

	let {
		type = 'button',
		disabled = false,
		loading = false,
		children,
		...attributes
	}: Omit<HTMLButtonAttributes, 'class'> & { loading?: boolean } = $props();
</script>

<button
	{...attributes}
	{type}
	disabled={disabled || loading}
	aria-busy={loading || undefined}
	class="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-900 hover:bg-slate-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-700 disabled:opacity-50"
>
	{@render children?.()}
</button>
