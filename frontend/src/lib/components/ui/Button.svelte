<script lang="ts">
	import type { HTMLButtonAttributes } from 'svelte/elements';

	let {
		type = 'button',
		disabled = false,
		loading = false,
		primary = false,
		children,
		...attributes
	}: Omit<HTMLButtonAttributes, 'class'> & { loading?: boolean; primary?: boolean } = $props();
</script>

<button
	{...attributes}
	{type}
	disabled={disabled || loading}
	aria-busy={loading || undefined}
	class={[
		'rounded-lg border px-3 py-2 text-sm font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-50',
		primary
			? 'border-b-4 border-action border-b-action-edge bg-action text-action-ink enabled:hover:bg-action-hover'
			: 'border-control-line bg-raised text-ink enabled:hover:bg-panel'
	]}
>
	{@render children?.()}
</button>
