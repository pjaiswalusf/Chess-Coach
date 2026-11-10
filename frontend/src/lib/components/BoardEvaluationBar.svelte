<script lang="ts">
	import { evaluationLabel, type PositionScore } from '#lib/utils/display.js';

	let { score, orientation }: { score: PositionScore | undefined; orientation: 'white' | 'black' } =
		$props();

	const cp = $derived(score?.cp ?? null);
	const mate = $derived(score?.mate ?? null);
	const whiteWins = $derived(score?.whiteWins ?? null);
	const available = $derived(cp !== null || whiteWins !== null);
	const whiteAtBottom = $derived(orientation === 'white');
	const whiteLeads = $derived(cp === null ? whiteWins === true : cp >= 0);
	const scoreAtBottom = $derived(available && whiteAtBottom === whiteLeads);
	const whiteShare = $derived(
		cp !== null ? Math.max(2, Math.min(98, 50 + 50 * Math.tanh(cp / 500))) : whiteWins ? 100 : 0
	);
	const compact = $derived.by(() => {
		if (mate !== null) return mate === 0 ? '#' : `M${Math.abs(mate)}`;
		if (cp === null) return '—';
		const pawns = Math.abs(cp) / 100;
		return pawns.toFixed(pawns < 10 ? 1 : 0);
	});
	const label = $derived(
		available
			? `Position evaluation: ${evaluationLabel(cp, mate, whiteWins)} (White perspective)`
			: 'Position evaluation unavailable'
	);
</script>

<div
	role="img"
	aria-label={label}
	title={label}
	class="relative self-stretch overflow-hidden rounded-sm border border-line bg-panel"
>
	{#if available}
		<svg
			aria-hidden="true"
			viewBox="0 0 1 100"
			preserveAspectRatio="none"
			class="absolute inset-0 size-full"
		>
			<rect
				x="0"
				y={whiteAtBottom ? 100 - whiteShare : 0}
				width="1"
				height={whiteShare}
				class="fill-stone-50"
			/>
		</svg>
	{/if}
	<span
		aria-hidden="true"
		class={[
			'absolute inset-x-0 text-center text-[0.625rem] leading-none font-bold tabular-nums sm:text-xs',
			scoreAtBottom ? 'bottom-1.5' : 'top-1.5',
			available && whiteLeads ? 'text-stone-900' : 'text-stone-50'
		]}>{compact}</span
	>
</div>
