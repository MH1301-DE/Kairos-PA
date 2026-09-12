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

	let garminConnection = $derived(data.connections.find((c) => c.connector === 'garmin'));
	let calendarConnection = $derived(data.connections.find((c) => c.connector === 'google_calendar'));

	let menuOpen = $state(false);
	let menuRoot: HTMLDivElement | undefined = $state();

	// below 640px, both the desktop popup and the nav links collapse into one
	// full-screen drawer (see the .hamburger-btn below) instead of two separate
	// triggers
	let mobileMenuOpen = $state(false);

	function handleWindowClick(event: MouseEvent) {
		if (menuOpen && menuRoot && !menuRoot.contains(event.target as Node)) {
			menuOpen = false;
		}
	}

	function handleKeydown(event: KeyboardEvent) {
		if (event.key === 'Escape') {
			menuOpen = false;
			mobileMenuOpen = false;
		}
	}

	const NAV_ITEMS = [
		{ href: '/', label: 'Dashboard' },
		{ href: '/calendar', label: 'Kalender' },
		{ href: '/goals', label: 'Ziele' },
		{ href: '/memory', label: 'Gedächtnis' },
		{ href: '/chat', label: 'Chat' }
	] as const;
</script>

{#snippet accountMenuContent()}
	<div class="menu-section">
		<h3>Verbindungen</h3>
		<div class="menu-row">
			<span>Garmin</span>
			<span class="badge" class:badge-ok={garminConnection?.status === 'active'}>
				{garminConnection ? garminConnection.status : 'nicht verbunden'}
			</span>
		</div>
		<div class="menu-row">
			<span>Google Kalender</span>
			<span class="badge" class:badge-ok={calendarConnection?.status === 'active'}>
				{calendarConnection ? calendarConnection.status : 'nicht verbunden'}
			</span>
		</div>
		<a
			href={resolve('/account')}
			class="menu-link menu-status-link"
			onclick={() => (mobileMenuOpen = false)}>Konto-Einstellungen</a
		>
	</div>

	<div class="menu-section">
		<h3>Datenabgleich</h3>
		<a
			href={resolve('/sync')}
			class="btn btn-secondary menu-action"
			onclick={() => (mobileMenuOpen = false)}>Zur Sync-Seite</a
		>
	</div>

	<div class="menu-section">
		<form method="POST" action="/auth/logout">
			<button type="submit" class="btn btn-ghost menu-action">Abmelden</button>
		</form>
	</div>
{/snippet}

<svelte:window onclick={handleWindowClick} onkeydown={handleKeydown} />

<svelte:head>
	<link rel="icon" href={favicon} />
	<!-- eslint-disable-next-line svelte/no-at-html-tags -->
	{@html webManifestLink}
</svelte:head>

<div class="shell">
	<nav>
		<a href={resolve('/')} class="wordmark">Kairos</a>
		<div class="nav-links">
			{#each NAV_ITEMS as item (item.href)}
				<a href={resolve(item.href)}>{item.label}</a>
			{/each}
		</div>
		{#if data.authenticated}
			<div class="menu-root" bind:this={menuRoot}>
				<button
					type="button"
					class="btn btn-ghost menu-trigger"
					aria-expanded={menuOpen}
					onclick={() => (menuOpen = !menuOpen)}
				>
					Konto & Sync ▾
				</button>
				{#if menuOpen}
					<div class="menu-panel" role="menu">
						{@render accountMenuContent()}
					</div>
				{/if}
			</div>
			<button
				type="button"
				class="hamburger-btn"
				aria-expanded={mobileMenuOpen}
				aria-label="Menü öffnen"
				onclick={() => (mobileMenuOpen = true)}
			>
				<span></span><span></span><span></span>
			</button>
		{/if}
	</nav>

	{#if mobileMenuOpen}
		<div class="mobile-drawer" role="dialog" aria-modal="true">
			<div class="mobile-drawer-header">
				<span class="wordmark">Kairos</span>
				<button
					type="button"
					class="btn btn-ghost"
					aria-label="Menü schließen"
					onclick={() => (mobileMenuOpen = false)}
				>
					✕
				</button>
			</div>
			<div class="mobile-drawer-links">
				{#each NAV_ITEMS as item (item.href)}
					<a href={resolve(item.href)} onclick={() => (mobileMenuOpen = false)}>{item.label}</a>
				{/each}
			</div>
			<div class="mobile-drawer-account">
				{@render accountMenuContent()}
			</div>
		</div>
	{/if}

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
	.wordmark:hover,
	.wordmark:focus-visible {
		text-decoration: none;
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
	.menu-root {
		position: relative;
	}
	.menu-trigger {
		font-size: var(--text-sm);
	}
	.menu-panel {
		position: absolute;
		right: 0;
		top: calc(100% + var(--space-2));
		width: 20rem;
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md, 8px);
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15);
		padding: var(--space-4);
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		z-index: 50;
	}
	.menu-section {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.menu-section h3 {
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--color-text-muted);
		margin: 0;
	}
	.menu-row {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-sm);
	}
	.menu-row span:first-child {
		flex: 1;
	}
	.badge {
		font-size: var(--text-xs);
		padding: 0.1rem 0.5rem;
		border-radius: 999px;
		background: var(--color-border);
		color: var(--color-text-muted);
	}
	.badge-ok {
		background: color-mix(in srgb, var(--color-accent) 20%, transparent);
		color: var(--color-accent);
	}
	.menu-link {
		font-size: var(--text-xs);
	}
	.menu-status-link {
		align-self: flex-start;
	}
	.menu-action {
		width: 100%;
		text-align: left;
	}
	form:has(.menu-action) {
		display: contents;
	}
	main {
		padding: var(--space-6);
		max-width: 72rem;
		margin: 0 auto;
	}

	/* hamburger trigger -- hidden by default, only shown below 640px */
	.hamburger-btn {
		display: none;
		flex-direction: column;
		justify-content: center;
		align-items: center;
		gap: 4px;
		width: 44px;
		height: 44px;
		background: transparent;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		cursor: pointer;
		padding: 0;
	}
	.hamburger-btn span {
		display: block;
		width: 18px;
		height: 2px;
		background: var(--color-text-muted);
		border-radius: 1px;
	}

	.mobile-drawer {
		display: none;
	}

	@media (max-width: 640px) {
		nav {
			gap: var(--space-4);
			padding: var(--space-3) var(--space-4);
		}
		.nav-links,
		.menu-root {
			display: none;
		}
		.hamburger-btn {
			display: flex;
		}
		.mobile-drawer {
			display: flex;
			flex-direction: column;
			position: fixed;
			inset: 0;
			z-index: 100;
			background: var(--color-bg);
			padding: var(--space-4);
			padding-top: max(var(--space-4), env(safe-area-inset-top));
			padding-bottom: max(var(--space-4), env(safe-area-inset-bottom));
			overflow-y: auto;
		}
		.mobile-drawer-header {
			display: flex;
			align-items: center;
			justify-content: space-between;
			margin-bottom: var(--space-6);
		}
		.mobile-drawer-links {
			display: flex;
			flex-direction: column;
			gap: var(--space-1);
			margin-bottom: var(--space-6);
		}
		.mobile-drawer-links a {
			padding: var(--space-3) var(--space-2);
			font-size: var(--text-lg);
			color: var(--color-text);
			border-radius: var(--radius-sm);
		}
		.mobile-drawer-links a:hover,
		.mobile-drawer-links a:focus-visible {
			background: var(--color-surface-raised);
			text-decoration: none;
		}
		.mobile-drawer-account {
			display: flex;
			flex-direction: column;
			gap: var(--space-4);
			padding-top: var(--space-4);
			border-top: 1px solid var(--color-border);
		}
	}
</style>
