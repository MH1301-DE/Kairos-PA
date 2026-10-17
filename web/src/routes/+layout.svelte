<script lang="ts">
	import '../app.css';
	import favicon from '$lib/assets/favicon.svg';
	import { resolve } from '$app/paths';
	import { onMount } from 'svelte';
	import { pwaInfo } from 'virtual:pwa-info';
	import type { LayoutData } from './$types';
	import type { Snippet } from 'svelte';
	import { page } from '$app/state';
	import FreshnessIndicator from '$lib/components/FreshnessIndicator.svelte';
	import { freshness } from '$lib/design/freshness';

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
	let calendarConnection = $derived(
		data.connections.find((c) => c.connector === 'google_calendar')
	);
	let fresh = $derived(freshness(garminConnection, data.jobs ?? []));

	const CONNECTION_LABELS: Record<string, string> = {
		active: 'verbunden',
		reauth_required: 'Anmeldung abgelaufen',
		disabled: 'getrennt',
		error: 'Fehler'
	};

	function connectionTone(status: string | undefined) {
		if (status === 'reauth_required' || status === 'error') return 'badge-danger';
		if (status === undefined || status === 'disabled') return 'badge-warning';
		return '';
	}

	function isActive(href: string): boolean {
		return href === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(href);
	}

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
		{ href: '/', label: 'Übersicht' },
		{ href: '/calendar', label: 'Kalender' },
		{ href: '/goals', label: 'Ziele' },
		{ href: '/memory', label: 'Gedächtnis' },
		{ href: '/chat', label: 'Chat' },
		{ href: '/scheduler', label: 'Scheduler' }
	] as const;

	// a failed last run of an active job shows a dot on the "Scheduler" entry
	function hasAlert(href: string): boolean {
		return href === '/scheduler' && (data.schedulerFailed ?? 0) > 0;
	}
</script>

{#snippet accountMenuContent()}
	<div class="menu-section">
		<h3>Verbindungen</h3>
		<div class="menu-row">
			<span>Garmin</span>
			<span class="badge {connectionTone(garminConnection?.status)}">
				{garminConnection
					? (CONNECTION_LABELS[garminConnection.status] ?? garminConnection.status)
					: 'nicht verbunden'}
			</span>
		</div>
		<div class="menu-row">
			<span>Google Kalender</span>
			<span class="badge {connectionTone(calendarConnection?.status)}">
				{calendarConnection
					? (CONNECTION_LABELS[calendarConnection.status] ?? calendarConnection.status)
					: 'nicht verbunden'}
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
				<a
					href={resolve(item.href)}
					class:active={isActive(item.href)}
					aria-current={isActive(item.href) ? 'page' : undefined}
					>{item.label}{#if hasAlert(item.href)}<span
							class="alert-dot"
							title="Ein geplanter Lauf ist fehlgeschlagen"
							aria-label="Ein geplanter Lauf ist fehlgeschlagen"
						></span>{/if}</a
				>
			{/each}
		</div>
		{#if fresh}
			<div class="freshness-slot"><FreshnessIndicator value={fresh} /></div>
		{/if}
		{#if data.authenticated}
			<div class="menu-root" bind:this={menuRoot}>
				<button
					type="button"
					class="btn btn-secondary menu-trigger"
					aria-expanded={menuOpen}
					onclick={() => (menuOpen = !menuOpen)}
				>
					Konto & Sync ▾
				</button>
				{#if menuOpen}
					<div class="menu-panel overlay" role="menu">
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
					<a
						href={resolve(item.href)}
						class:active={isActive(item.href)}
						onclick={() => (mobileMenuOpen = false)}
						>{item.label}{#if hasAlert(item.href)}<span
								class="alert-dot"
								aria-label="Ein geplanter Lauf ist fehlgeschlagen"
							></span>{/if}</a
					>
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
		height: var(--size-header-desktop);
		padding: 0 var(--space-8);
	}
	.wordmark {
		font: var(--type-subtitle);
		color: var(--text);
		letter-spacing: -0.01em;
	}
	.wordmark:hover {
		color: var(--text);
	}
	.nav-links {
		display: flex;
		gap: var(--space-1);
		flex: 1;
	}
	.nav-links a {
		color: var(--text-secondary);
		font: var(--type-body-sm);
		padding: var(--space-2) 14px;
		border-radius: var(--radius-pill);
		transition:
			background var(--motion-fast) var(--motion-easing),
			color var(--motion-fast) var(--motion-easing);
	}
	.nav-links a:hover {
		color: var(--text);
		background: var(--surface);
	}
	.nav-links a.active {
		color: var(--accent);
		background: var(--accent-subtle);
	}
	/* triangle mark like StatusPill's deviation tone: shape, not color alone */
	.alert-dot {
		display: inline-block;
		width: 0;
		height: 0;
		margin-left: 6px;
		vertical-align: middle;
		border-left: 4px solid transparent;
		border-right: 4px solid transparent;
		border-bottom: 7px solid var(--status-deviation-mark);
	}
	.menu-root {
		position: relative;
	}
	.menu-panel {
		position: absolute;
		right: 0;
		top: calc(100% + var(--space-2));
		width: 20rem;
		padding: var(--space-4);
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
		z-index: 50;
	}
	.menu-section {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.menu-section h3 {
		font: var(--type-caption);
		color: var(--text-muted);
		margin: 0;
	}
	.menu-row {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font: var(--type-body-sm);
	}
	.menu-row span:first-child {
		flex: 1;
	}
	.menu-row .badge {
		margin-top: 0;
	}
	.menu-link {
		font: var(--type-caption);
	}
	.menu-status-link {
		align-self: flex-start;
	}
	.menu-action {
		width: 100%;
		justify-content: flex-start;
	}
	/* the overlay is already surface-raised, so lift the secondary button one step */
	.menu-panel .btn-secondary,
	.mobile-drawer .btn-secondary {
		background: var(--line-subtle);
	}
	form:has(.menu-action) {
		display: contents;
	}
	main {
		padding: var(--space-6) var(--space-8) var(--space-16);
		max-width: 90rem;
		margin: 0 auto;
	}

	/* hamburger trigger -- hidden by default, only shown below 640px */
	.hamburger-btn {
		display: none;
		flex-direction: column;
		justify-content: center;
		align-items: center;
		gap: 4px;
		width: var(--size-tap-min);
		height: var(--size-tap-min);
		background: var(--surface);
		border: none;
		border-radius: var(--radius-pill);
		cursor: pointer;
		padding: 0;
	}
	.hamburger-btn span {
		display: block;
		width: 18px;
		height: 2px;
		background: var(--text-secondary);
		border-radius: 1px;
	}

	.mobile-drawer {
		display: none;
	}

	@media (max-width: 960px) {
		.freshness-slot {
			display: none;
		}
	}

	@media (max-width: 640px) {
		nav {
			gap: var(--space-4);
			height: var(--size-header-mobile);
			padding: 0 var(--space-4);
			justify-content: space-between;
		}
		.nav-links,
		.menu-root {
			display: none;
		}
		.hamburger-btn {
			display: flex;
		}
		main {
			padding: var(--space-4) var(--space-4) var(--space-12);
		}
		.mobile-drawer {
			display: flex;
			flex-direction: column;
			position: fixed;
			inset: 0;
			z-index: 100;
			background: var(--bg);
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
			padding: var(--space-3) var(--space-4);
			font: var(--type-subtitle);
			font-weight: 400;
			color: var(--text);
			border-radius: var(--radius-md);
		}
		.mobile-drawer-links a:hover {
			background: var(--surface);
		}
		.mobile-drawer-links a.active {
			color: var(--accent);
			background: var(--accent-subtle);
		}
		.mobile-drawer-account {
			display: flex;
			flex-direction: column;
			gap: var(--space-5);
			padding: var(--space-5) var(--space-4);
			background: var(--surface);
			border-radius: var(--radius-lg);
		}
	}
</style>
