<script lang="ts">
	import { resolve } from '$app/paths';
	import './layout.css';
	import { page } from '$app/state';
	import favicon from '#lib/assets/favicon.svg';
	import HealthStatus from '#lib/components/HealthStatus.svelte';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();

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
	class="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-10 focus:rounded-lg focus:bg-white focus:p-3 focus:text-slate-950"
	>Skip to content</a
>

<div
	class="mx-auto grid min-h-screen max-w-7xl grid-rows-[auto_1fr] bg-slate-50 text-slate-900 md:grid-cols-[12rem_minmax(0,1fr)] md:grid-rows-1"
>
	<div class="border-b border-slate-200 bg-white p-4 md:border-r md:border-b-0 md:p-6">
		<p class="mb-3 text-lg font-bold tracking-tight text-emerald-900 md:mb-6">Chess Coach</p>
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
					class="rounded-lg px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100 focus-visible:outline-2 focus-visible:outline-emerald-700 [&[aria-current]]:bg-emerald-100 [&[aria-current]]:text-emerald-900"
					>{item.label}</a
				>
			{/each}
		</nav>
	</div>
	<div class="min-w-0">
		<header class="border-b border-slate-200 bg-white px-4 py-3 md:px-8">
			<HealthStatus />
		</header>
		<main id="main-content" tabindex="-1" class="mx-auto max-w-5xl space-y-6 p-4 md:p-8">
			{@render children()}
		</main>
	</div>
</div>
