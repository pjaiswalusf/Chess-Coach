<script lang="ts">
	const tones = {
		positive: 'bg-positive-surface text-accent',
		caution: 'bg-warning-surface text-warning',
		negative: 'bg-danger-surface text-danger',
		neutral: 'bg-raised text-ink'
	};
	let { label, tone = 'neutral' }: { label: string; tone?: keyof typeof tones } = $props();
</script>

<span class={['inline-block rounded-full px-2.5 py-1 text-sm font-semibold', tones[tone]]}>
	{label}
</span>
