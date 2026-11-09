<script lang="ts">
	const tones = {
		positive: 'bg-emerald-100 text-emerald-900',
		caution: 'bg-amber-100 text-amber-900',
		negative: 'bg-red-100 text-red-900',
		neutral: 'bg-slate-100 text-slate-800'
	};
	let { label, tone = 'neutral' }: { label: string; tone?: keyof typeof tones } = $props();
</script>

<span class={['inline-block rounded-full px-2.5 py-1 text-sm font-semibold', tones[tone]]}>
	{label}
</span>
