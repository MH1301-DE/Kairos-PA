<script lang="ts">
	import '../app.css';
	import favicon from '$lib/assets/favicon.svg';
	import { resolve } from '$app/paths';
	import { enhance } from '$app/forms';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { pwaInfo } from 'virtual:pwa-info';
	import type { LayoutData } from './$types';
	import type { Snippet } from 'svelte';

	let { data, children }: { data: LayoutData; children: Snippet } = $props();
	// the menu's forms live in the layout but their actions are declared on
	// the dashboard's +page.server.ts (SvelteKit only allows actions there) --
	// page.form is how a layout observes a page-level action's result
	let menuForm = $derived(page.form as { menuError?: string; menuTriggered?: string } | null);

	// vite-plugin-pwa emits the manifest link tag as a raw HTML string
	let webManifestLink = $derived(pwaInfo ? pwaInfo.webManifest.linkTag : '');

	onMount(async () => {
		if ('serviceWorker' in navigator) {
			const { registerSW } = await import('virtual:pwa-register');
			registerSW({ immediate: true });
		}
	});

	const ACTIVE_STATUSES = new Set(['queued', 'running']);
	let garminConnection = $derived(data.connections.find((c) => c.connector === 'garmin'));
	let calendarConnection = $derived(data.connections.find((c) => c.connector === 'google_calendar'));
	let hasActiveGarminJob = $derived(
		data.jobs.some((j) => j.connector === 'garmin' && ACTIVE_STATUSES.has(j.status))
	);
	let hasActiveCalendarJob = $derived(
		data.jobs.some((j) => j.connector === 'google_calendar' && ACTIVE_STATUSES.has(j.status))
	);

	let menuOpen = $state(false);
	let menuRoot: HTMLDivElement | undefined = $state();
	let triggeringGarmin = $state(false);
	let triggeringCalendar = $state(false);

	function handleWindowClick(event: MouseEvent) {
		if (menuOpen && menuRoot && !menuRoot.contains(event.target as Node)) {
			menuOpen = false;
		}
	}

	function handleKeydown(event: KeyboardEvent) {
		if (event.key === 'Escape') menuOpen = false;
	}
</script>

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
			<a href={resolve('/')}>Dashboard</a>
			<a href={resolve('/calendar')}>Kalender</a>
			<a href={resolve('/goals')}>Ziele</a>
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
							<a href={resolve('/account')} class="menu-link menu-status-link"
								>Konto-Einstellungen</a
							>
						</div>

						<div class="menu-section">
							<h3>Datenabgleich</h3>
							<form
								method="POST"
								action="/?/triggerGarminBackfill"
								use:enhance={() => {
									triggeringGarmin = true;
									return async ({ update }) => {
										await update();
										triggeringGarmin = false;
									};
								}}
							>
								<button
									type="submit"
									class="btn btn-secondary menu-action"
									disabled={triggeringGarmin || hasActiveGarminJob}
								>
									{hasActiveGarminJob
										? 'Garmin-Backfill läuft …'
										: triggeringGarmin
											? 'Startet …'
											: 'Garmin-Backfill starten'}
								</button>
							</form>
							<form
								method="POST"
								action="/?/triggerCalendarSync"
								use:enhance={() => {
									triggeringCalendar = true;
									return async ({ update }) => {
										await update();
										triggeringCalendar = false;
									};
								}}
							>
								<button
									type="submit"
									class="btn btn-secondary menu-action"
									disabled={triggeringCalendar || hasActiveCalendarJob}
								>
									{hasActiveCalendarJob
										? 'Kalender-Sync läuft …'
										: triggeringCalendar
											? 'Startet …'
											: 'Kalender synchronisieren'}
								</button>
							</form>
							<a href={resolve('/sync')} class="menu-link menu-status-link">Sync-Status im Detail</a>
							{#if menuForm?.menuError}
								<p class="status-error">{menuForm.menuError}</p>
							{/if}
						</div>

						<div class="menu-section">
							<form method="POST" action="/auth/logout">
								<button type="submit" class="btn btn-ghost menu-action">Abmelden</button>
							</form>
						</div>
					</div>
				{/if}
			</div>
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
</style>
