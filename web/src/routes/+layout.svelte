<script lang="ts">
	import '../app.css';
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

<div class="shell">
	<nav>
		<span class="wordmark">Kairos</span>
		<div class="nav-links">
			<a href={resolve('/')}>Dashboard</a>
			<a href={resolve('/sync')}>Sync-Status</a>
			<a href={resolve('/onboarding')}>Garmin verbinden</a>
		</div>
		{#if data.authenticated}
			<form method="POST" action="/auth/logout">
				<button type="submit" class="btn btn-ghost">Abmelden</button>
			</form>
		{/if}
	</nav>

	<main>
		{@render children()}
	</main>
</div>

<style>
	.shell {
		min-height: 100vh;
	}
	nav {
		display: flex;
		align-items: center;
		gap: var(--space-6);
		padding: var(--space-4) var(--space-6);
		border-bottom: 1px solid var(--color-border);
	}
	.wordmark {
		font-family: var(--font-display);
		font-size: var(--text-lg);
		font-weight: 600;
		color: var(--color-accent);
		letter-spacing: -0.01em;
	}
	.nav-links {
		display: flex;
		gap: var(--space-5);
		flex: 1;
	}
	.nav-links a {
		color: var(--color-text-muted);
		font-size: var(--text-sm);
		font-weight: 500;
	}
	.nav-links a:hover,
	.nav-links a:focus-visible {
		color: var(--color-text);
		text-decoration: none;
	}
	main {
		padding: var(--space-6);
		max-width: 72rem;
		margin: 0 auto;
	}
</style>
