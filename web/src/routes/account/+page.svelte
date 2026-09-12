<!-- web/src/routes/account/+page.svelte -->
<script lang="ts">
	import { resolve } from '$app/paths';
	import type { ConnectionInfo } from '$lib/types';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();

	interface ConnectorMeta {
		id: string;
		title: string;
		// /onboarding is a SvelteKit page (resolve()'d below); /auth/login is a
		// backend route proxied through, not a SvelteKit route, so it's a plain href
		manageHref: '/onboarding' | '/auth/login';
		manageLabel: string;
	}

	// fixed order/labels regardless of which connectors the user has actually
	// set up -- an unconnected connector still gets a card with a connect link
	const CONNECTORS: ConnectorMeta[] = [
		{ id: 'garmin', title: 'Garmin', manageHref: '/onboarding', manageLabel: 'Bearbeiten' },
		{
			id: 'google_calendar',
			title: 'Google Kalender',
			manageHref: '/auth/login',
			manageLabel: 'Neu verbinden'
		}
	];

	function connectionFor(id: string): ConnectionInfo | undefined {
		return data.connections.find((c) => c.connector === id);
	}

	function formatDateTime(iso: string): string {
		return new Date(iso).toLocaleString('de-DE');
	}

	const STATUS_LABELS: Record<string, string> = {
		active: 'aktiv',
		reauth_required: 'Neuanmeldung nötig',
		disabled: 'deaktiviert',
		error: 'Fehler'
	};
</script>

<h1>Konto-Einstellungen</h1>
<p class="intro">Verbundene Konten, ihr Status und seit wann sie eingerichtet sind.</p>

<div class="connector-grid">
	{#each CONNECTORS as meta (meta.id)}
		{@const connection = connectionFor(meta.id)}
		<div class="tile connector-card">
			<div class="connector-header">
				<h2>{meta.title}</h2>
				<span class="badge" class:badge-ok={connection?.status === 'active'}>
					{connection ? (STATUS_LABELS[connection.status] ?? connection.status) : 'nicht verbunden'}
				</span>
			</div>

			{#if connection}
				<dl>
					{#if connection.external_account}
						<dt>Konto</dt>
						<dd>{connection.external_account}</dd>
					{/if}
					<dt>Verbunden seit</dt>
					<dd class="figure">{formatDateTime(connection.connected_at)}</dd>
				</dl>
			{:else}
				<p class="empty">Noch nicht eingerichtet.</p>
			{/if}

			{#if meta.manageHref === '/onboarding'}
				<a href={resolve('/onboarding')} class="btn btn-secondary">
					{connection ? meta.manageLabel : 'Jetzt verbinden'}
				</a>
			{:else}
				<a href={meta.manageHref} class="btn btn-secondary">
					{connection ? meta.manageLabel : 'Jetzt verbinden'}
				</a>
			{/if}
		</div>
	{/each}
</div>

<h2 class="section-title">Chat-Assistent</h2>
<div class="tile llm-note">
	<p>
		Der LLM-Anbieter gilt für die gesamte Kairos-Installation, nicht pro Konto — wird von
		der Person eingerichtet, die den Server betreibt (<code>LLM_API_KEY</code> in
		<code>.env</code>).
	</p>
</div>

<style>
	.intro {
		color: var(--color-text-muted);
		margin-bottom: var(--space-5);
	}
	.connector-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
		gap: var(--space-4);
	}
	.connector-card {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
	}
	.connector-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-2);
	}
	.connector-header h2 {
		font-size: var(--text-lg);
		margin: 0;
	}
	dl {
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}
	dt {
		font-size: var(--text-xs);
		color: var(--color-text-muted);
	}
	dd {
		margin: 0 0 var(--space-2);
	}
	.connector-card .btn {
		align-self: flex-start;
	}
	.section-title {
		font-size: var(--text-lg);
		margin: var(--space-6) 0 var(--space-3);
	}
	.llm-note {
		max-width: 32rem;
		color: var(--color-text-muted);
	}
	.llm-note code {
		font-family: var(--font-mono);
		background: var(--color-surface-raised);
		padding: 0.1rem 0.3rem;
		border-radius: var(--radius-sm);
	}
</style>
