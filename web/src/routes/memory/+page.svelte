<!-- web/src/routes/memory/+page.svelte -->
<script lang="ts">
	import { enhance } from '$app/forms';
	import { SvelteSet } from 'svelte/reactivity';
	import type { PageData, ActionData } from './$types';

	let { data, form }: { data: PageData; form: ActionData } = $props();

	let showForm = $state(false);
	// ids currently in edit mode -- a Set so multiple rows could in principle be
	// edited at once, mirrors the goals page's single showForm toggle but per-row
	let editingIds = new SvelteSet<string>();

	function startEdit(id: string) {
		editingIds.add(id);
	}
	function cancelEdit(id: string) {
		editingIds.delete(id);
	}

	function formatDate(iso: string): string {
		return new Date(iso).toLocaleString('de-DE', {
			day: '2-digit',
			month: '2-digit',
			year: 'numeric',
			hour: '2-digit',
			minute: '2-digit'
		});
	}
</script>

<h1>Gedächtnis</h1>
<p class="lede">
	Was sich Kairos über dich merkt. Einträge, die der Agent selbst anlegt, sind mit "von Kairos"
	markiert -- du kannst jeden Eintrag hier ansehen, bearbeiten oder löschen.
</p>

<div class="tile">
	<button type="button" class="btn btn-secondary" onclick={() => (showForm = !showForm)}>
		{showForm ? 'Abbrechen' : '+ Neuer Eintrag'}
	</button>

	{#if showForm}
		<form
			method="POST"
			action="?/create"
			use:enhance={() => {
				return async ({ update }) => {
					await update();
					showForm = false;
				};
			}}
			class="memory-form"
		>
			<label class="field">
				Text
				<textarea name="content" rows="2" placeholder="z.B. trainiert ungern vor 7 Uhr" required
				></textarea>
			</label>
			{#if form?.createError}
				<p class="status-error">{form.createError}</p>
			{/if}
			<button type="submit" class="btn btn-primary">Speichern</button>
		</form>
	{/if}
</div>

<div class="tile">
	{#if data.entries.length === 0}
		<p class="empty">Noch nichts gemerkt.</p>
	{:else}
		<ul class="memory-list">
			{#each data.entries as entry (entry.id)}
				<li class="memory-row">
					{#if editingIds.has(entry.id)}
						<form
							method="POST"
							action="?/update"
							use:enhance={() => {
								return async ({ update }) => {
									await update();
									cancelEdit(entry.id);
								};
							}}
							class="edit-form"
						>
							<input type="hidden" name="memory_id" value={entry.id} />
							<textarea name="content" rows="2">{entry.content}</textarea>
							<div class="edit-actions">
								<button type="submit" class="btn btn-primary btn-small">Speichern</button>
								<button
									type="button"
									class="btn btn-ghost btn-small"
									onclick={() => cancelEdit(entry.id)}
								>
									Abbrechen
								</button>
							</div>
						</form>
					{:else}
						<div class="memory-content">
							<span class="badge">
								{entry.source === 'agent' ? 'von Kairos' : 'von dir'}
							</span>
							<p>{entry.content}</p>
							<span class="memory-meta">Zuletzt geändert: {formatDate(entry.updated_at)}</span>
						</div>
						<div class="memory-actions">
							<button
								type="button"
								class="btn btn-ghost btn-small"
								onclick={() => startEdit(entry.id)}
							>
								Bearbeiten
							</button>
							<form method="POST" action="?/remove" use:enhance>
								<input type="hidden" name="memory_id" value={entry.id} />
								<button type="submit" class="btn btn-ghost btn-small">Löschen</button>
							</form>
						</div>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}
	{#if form?.updateError}
		<p class="status-error">{form.updateError}</p>
	{/if}
	{#if form?.deleteError}
		<p class="status-error">{form.deleteError}</p>
	{/if}
</div>

<style>
	.lede {
		color: var(--color-text-muted);
		max-width: 36rem;
	}
	.memory-form {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		margin-top: var(--space-4);
		max-width: 32rem;
	}
	.memory-form textarea,
	.edit-form textarea {
		font: inherit;
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		padding: var(--space-2);
		color: var(--color-text);
		resize: vertical;
	}
	.memory-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.memory-row {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--space-4);
		padding: var(--space-3) 0;
		border-bottom: 1px solid var(--color-border-subtle);
	}
	.memory-content {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}
	.memory-content p {
		margin: 0;
	}
	.memory-meta {
		font-size: var(--text-xs);
		color: var(--color-text-muted);
	}
	.memory-actions {
		display: flex;
		gap: var(--space-2);
		flex-shrink: 0;
	}
	.edit-form {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		width: 100%;
	}
	.edit-actions {
		display: flex;
		gap: var(--space-2);
	}
	.badge {
		align-self: flex-start;
		margin-top: 0;
	}
</style>
