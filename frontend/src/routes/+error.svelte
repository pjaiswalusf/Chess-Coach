<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import Card from '#lib/components/ui/Card.svelte';

	const notFound = $derived(page.status === 404);
</script>

<svelte:head
	><title>{notFound ? 'Page not found' : 'Something went wrong'} · Chess Coach</title></svelte:head
>

<Card>
	<h1 class="text-3xl font-semibold tracking-tight">
		{notFound ? 'Page not found' : 'Something went wrong'}
	</h1>
	<p class="text-slate-600">
		{notFound
			? 'The requested page does not exist.'
			: 'The application couldn’t display this page.'}
	</p>
	<a href={resolve('/')} class="font-medium text-emerald-800 underline underline-offset-4"
		>Return to Dashboard</a
	>
</Card>
