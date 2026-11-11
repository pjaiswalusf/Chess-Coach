<script lang="ts">
	import { resolve } from '$app/paths';
	import './layout.css';
	import { page } from '$app/state';
	import favicon from '#lib/assets/favicon.svg';
	import HealthStatus from '#lib/components/HealthStatus.svelte';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();
	const reviewing = $derived(page.route.id === '/games/[id=gameId]');

	const navigation = [
		{ label: 'Dashboard', href: '/' },
		{ label: 'Sync', href: '/sync' },
		{ label: 'Games', href: '/games' },
		{ label: 'Coach', href: '/coach' },
		{ label: 'Training', href: '/training' },
		{ label: 'System', href: '/system' }
	] as const;
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

<a
	href="#main-content"
	class="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-10 focus:rounded-lg focus:bg-action focus:p-3 focus:text-action-ink"
	>Skip to content</a
>

<div
	class={[
		'mx-auto grid min-h-screen grid-rows-[auto_1fr] bg-canvas text-ink md:grid-cols-[12rem_minmax(0,1fr)] md:grid-rows-1',
		reviewing ? 'max-w-screen-2xl' : 'max-w-7xl'
	]}
>
	<div class="border-b border-line bg-sidebar p-4 md:border-r md:border-b-0 md:p-6">
		<p class="mb-3 text-lg font-bold tracking-tight text-accent md:mb-6">Chess Coach</p>
		<nav aria-label="Main navigation" class="flex flex-wrap gap-1 md:flex-col">
			{#each navigation as item (item.href)}
				{@const current =
					page.route.id === item.href
						? 'page'
						: item.href !== '/' && page.route.id?.startsWith(item.href + '/')
							? 'location'
							: undefined}
				<a
					href={resolve(item.href)}
					aria-current={current}
					class="rounded-lg px-3 py-2 text-sm font-semibold text-muted hover:bg-raised focus-visible:outline-2 focus-visible:outline-accent [&[aria-current]]:bg-positive-surface [&[aria-current]]:text-accent [&[aria-current]]:ring-1 [&[aria-current]]:ring-positive-line [&[aria-current]]:ring-inset"
					>{item.label}</a
				>
			{/each}
		</nav>
	</div>
	<div class="min-w-0">
		{#if page.route.id !== '/system'}
			<header class="border-b border-line bg-panel px-4 py-3 md:px-8">
				<HealthStatus />
			</header>
		{/if}
		<main
			id="main-content"
			tabindex="-1"
			class={['mx-auto space-y-6 p-4 md:p-8', !reviewing && 'max-w-5xl']}
		>
			{@render children()}
		</main>
	</div>
</div>
