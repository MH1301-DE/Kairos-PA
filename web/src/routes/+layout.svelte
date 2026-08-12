<script lang="ts">
	import favicon from '$lib/assets/favicon.svg';
	import { resolve } from '$app/paths';
	import { onMount } from 'svelte';
	import { pwaInfo } from 'virtual:pwa-info';
	import type { LayoutData } from './$types';
	import type { Snippet } from 'svelte';

	let { data, children }: { data: LayoutData; children: Snippet } = $props();

	// vite-plugin-pwa emits the manifest link tag as a raw HTML string
	let webManifestLink = $derived(pwaInfo ? pwaInfo.webManifest.linkTag : '');

	onMount(async () => {
		if ('serviceWorker' in navigator) {
			const { registerSW } = await import('virtual:pwa-register');
			registerSW({ immediate: true });
		}
	});
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
	<!-- eslint-disable-next-line svelte/no-at-html-tags -->
	{@html webManifestLink}
</svelte:head>

<nav>
	<a href={resolve('/')}>Dashboard</a>
	<a href={resolve('/sync')}>Sync-Status</a>
	<a href={resolve('/onboarding')}>Garmin verbinden</a>
	{#if data.authenticated}
		<form method="POST" action="/auth/logout" style="display: inline;">
			<button type="submit">Abmelden</button>
		</form>
	{/if}
</nav>

<main>
	{@render children()}
</main>

<style>
	nav {
		display: flex;
		gap: 1rem;
		padding: 1rem;
		border-bottom: 1px solid #e2e8f0;
	}
	main {
		padding: 1rem;
	}
</style>
