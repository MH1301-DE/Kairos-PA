<!-- web/src/routes/account/+page.svelte -->
<script lang="ts">
	import { enhance } from '$app/forms';
	import { resolve } from '$app/paths';
	import type { ConnectionInfo } from '$lib/types';
	import type { ActionData, PageData } from './$types';

	let { data, form }: { data: PageData; form: ActionData } = $props();

	let llmConnection = $derived(data.connections.find((c) => c.connector === 'llm_provider'));
	let submittingLlm = $state(false);

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
<div class="tile llm-card">
	<div class="connector-header">
		<h3>LLM-Anbieter</h3>
		<span class="badge" class:badge-ok={llmConnection?.status === 'active'}>
			{llmConnection ? 'aktiv' : 'nicht eingerichtet'}
		</span>
	</div>
	{#if llmConnection}
		<p class="empty">Aktuelles Modell: <span class="figure">{llmConnection.external_account}</span></p>
	{:else}
		<p class="empty">
			Ohne eigenen API-Key kann der Chat (/chat) noch nicht antworten.
		</p>
	{/if}

	<form
		method="POST"
		action="?/connectLlm"
		use:enhance={() => {
			submittingLlm = true;
			return async ({ update }) => {
				await update();
				submittingLlm = false;
			};
		}}
		class="llm-form"
	>
		<fieldset disabled={submittingLlm}>
			<label class="field">
				Modell
				<input
					type="text"
					name="model"
					value={llmConnection?.external_account ?? 'anthropic/claude-sonnet-5'}
					placeholder="anthropic/claude-sonnet-5"
					required
				/>
			</label>
			<label class="field">
				API-Key
				<!-- never pre-filled: the server does not echo the key back -->
				<input type="password" name="api_key" required />
			</label>
			{#if form?.llmError}
				<p class="status-error">{form.llmError}</p>
			{/if}
			{#if form?.llmSuccess}
				<p class="status-success">Gespeichert.</p>
			{/if}
			<button type="submit" class="btn btn-primary">
				{submittingLlm ? 'Speichert …' : llmConnection ? 'Aktualisieren' : 'Verbinden'}
			</button>
		</fieldset>
	</form>
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
	.llm-card {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		max-width: 24rem;
	}
	.connector-header h3 {
		font-size: var(--text-lg);
		margin: 0;
	}
	.llm-form fieldset {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		border: none;
		margin: 0;
		padding: 0;
	}
	.llm-form fieldset:disabled {
		opacity: 0.75;
	}
</style>
