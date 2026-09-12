<!-- web/src/routes/+page.svelte -->
<script lang="ts">
	import { invalidate } from '$app/navigation';
	import { enhance } from '$app/forms';
	import { untrack } from 'svelte';
	import { flip } from 'svelte/animate';
	import { dndzone } from 'svelte-dnd-action';
	import MetricTile from '$lib/components/MetricTile.svelte';
	import { MODULES, moduleById } from '$lib/modules';
	import { mergeTileAsOf, type TileState } from '$lib/dashboardTiles';
	import { orderModules } from '$lib/dashboardLayout';
	import type { MetricResult } from '$lib/types';
	import type { ActionData, PageData } from './$types';

	let { data, form }: { data: PageData; form: ActionData } = $props();

	function todayIso(): string {
		return new Date().toISOString().slice(0, 10);
	}

	// local, per-tile state (asOf override, latest fetched result) layered on
	// top of the server-loaded snapshot -- resynced whenever data.tiles
	// changes (i.e. after the "Aktualisieren" button re-runs load())
	let tiles = $state<TileState[]>([]);

	// a user-picked "Stand" date, kept outside $state so reading it here doesn't
	// make this effect depend on `tiles` itself (which it also writes to) --
	// see mergeTileAsOf's doc comment for why this exists
	const manualAsOf = new Map<string, string>();

	$effect(() => {
		tiles = mergeTileAsOf(data.tiles, manualAsOf, todayIso());
		// data.tiles is always today's snapshot -- any tile still pinned to an
		// earlier date needs its own fetch, or it'd show today's data under
		// yesterday's label. untrack() reads the just-assigned `tiles` (so
		// refetchTile mutates the real reactive elements, not a disconnected
		// copy) without making this effect depend on state it itself writes --
		// that self-dependency is what caused an infinite update loop before.
		untrack(() => {
			for (const tile of tiles) {
				if (tile.asOf !== todayIso()) refetchTile(tile);
			}
		});
	});

	// personalized order/visibility (Kacheln personalisieren) -- reorders and
	// filters the same `tiles` state above, no separate data fetch
	let visibleTiles = $derived.by(() => {
		const orderedIds = orderModules(MODULES, data.layout)
			.filter((t) => t.visible)
			.map((t) => t.module.moduleId);
		return orderedIds
			.map((id) => tiles.find((t) => t.moduleId === id))
			.filter((t): t is TileState => t !== undefined);
	});

	let refreshing = $state(false);

	async function refreshAll() {
		refreshing = true;
		try {
			// the daily-aggregate tables behind every tile don't update
			// themselves after a sync -- recompute before refetching, or
			// "refresh" would just re-show the same stale numbers
			await fetch('/api/metrics/recompute', { method: 'POST', credentials: 'include' });
		} catch {
			// recompute failures degrade to "tiles show whatever's already
			// aggregated" -- still worth refetching
		}
		await invalidate('dashboard:tiles');
		refreshing = false;
	}

	async function refetchTile(tile: TileState) {
		const module = moduleById(tile.moduleId);
		if (!module) return;
		manualAsOf.set(tile.moduleId, tile.asOf);
		tile.loading = true;
		try {
			const resp = await fetch(
				`/api/metrics/${tile.moduleId}?variant=${module.variant}&as_of=${tile.asOf}`,
				{ credentials: 'include' }
			);
			if (resp.ok) {
				tile.result = (await resp.json()) as MetricResult;
				tile.error = null;
			} else {
				tile.error = 'Daten gerade nicht verfügbar';
			}
		} catch {
			tile.error = 'Daten gerade nicht verfügbar';
		} finally {
			tile.loading = false;
		}
	}

	// -- Kachel-Personalisierung ("Anpassen") --

	interface EditItem {
		id: string;
		visible: boolean;
	}

	let editMode = $state(false);
	let editItems = $state<EditItem[]>([]);
	let savingLayout = $state(false);

	function enterEditMode() {
		editItems = orderModules(MODULES, data.layout).map((t) => ({
			id: t.module.moduleId,
			visible: t.visible
		}));
		editMode = true;
	}

	function handleDndConsider(e: CustomEvent<{ items: EditItem[] }>) {
		editItems = e.detail.items;
	}
	function handleDndFinalize(e: CustomEvent<{ items: EditItem[] }>) {
		editItems = e.detail.items;
	}

	function layoutPayload(): string {
		return JSON.stringify(
			editItems.map((item, i) => ({ module_id: item.id, position: i, visible: item.visible }))
		);
	}
</script>

<div class="dashboard-header">
	<h1>Dashboard</h1>
	{#if !editMode}
		<div class="header-actions">
			<button type="button" class="btn btn-ghost" onclick={enterEditMode}>Anpassen</button>
			<button type="button" class="btn btn-secondary" onclick={refreshAll} disabled={refreshing}>
				{refreshing ? 'Aktualisiert …' : '↻ Aktualisieren'}
			</button>
		</div>
	{/if}
</div>

{#if editMode}
	<form
		method="POST"
		action="?/saveLayout"
		use:enhance={() => {
			savingLayout = true;
			return async ({ update }) => {
				await update();
				savingLayout = false;
				editMode = false;
			};
		}}
	>
		<input type="hidden" name="layout" value={layoutPayload()} />
		<p class="edit-hint">Ziehen zum Sortieren, Häkchen zum Ein-/Ausblenden.</p>
		<div
			class="tile-grid edit-grid"
			use:dndzone={{ items: editItems, flipDurationMs: 200 }}
			onconsider={handleDndConsider}
			onfinalize={handleDndFinalize}
		>
			{#each editItems as item (item.id)}
				<div
					class="edit-tile"
					class:edit-tile-hidden={!item.visible}
					animate:flip={{ duration: 200 }}
				>
					<span class="drag-handle" aria-label="Ziehen zum Sortieren">⠿</span>
					<span class="edit-tile-title">{moduleById(item.id)?.title ?? item.id}</span>
					<label class="visibility-toggle">
						<input type="checkbox" bind:checked={item.visible} />
						sichtbar
					</label>
				</div>
			{/each}
		</div>
		{#if form?.layoutError}
			<p class="status-error">{form.layoutError}</p>
		{/if}
		<div class="edit-actions">
			<button type="submit" class="btn btn-primary" disabled={savingLayout}>
				{savingLayout ? 'Speichert …' : 'Speichern'}
			</button>
			<button type="button" class="btn btn-ghost" onclick={() => (editMode = false)}>
				Abbrechen
			</button>
		</div>
	</form>
{:else}
	<div class="tile-grid">
		{#each visibleTiles as tile (tile.moduleId)}
			{@const module = moduleById(tile.moduleId)}
			{#if module}
				<div class="tile-card">
					<label class="as-of-picker">
						Stand
						<input
							type="date"
							bind:value={tile.asOf}
							max={todayIso()}
							onchange={() => refetchTile(tile)}
						/>
					</label>
					{#if tile.loading}
						<div class="tile tile-loading">
							<div class="skeleton skeleton-title"></div>
							<div class="skeleton skeleton-body"></div>
						</div>
					{:else if tile.result}
						<MetricTile result={tile.result} {module} />
					{:else}
						<div class="tile-error">
							<h3>{module.title}</h3>
							<p>{tile.error}</p>
						</div>
					{/if}
				</div>
			{/if}
		{/each}
	</div>
{/if}

<style>
	.dashboard-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-4);
		margin-bottom: var(--space-4);
	}
	.header-actions {
		display: flex;
		gap: var(--space-2);
	}
	.tile-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
		gap: var(--space-4);
	}
	.tile-card {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.as-of-picker {
		align-self: flex-end;
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-xs);
		color: var(--color-text-muted);
	}
	.as-of-picker input {
		font-size: var(--text-xs);
		padding: 0.1rem 0.3rem;
	}
	.tile-loading {
		display: flex;
		flex-direction: column;
		flex: 1;
		gap: var(--space-3);
		min-height: 320px;
	}
	.skeleton-title {
		width: 60%;
		height: var(--text-lg);
	}
	.skeleton-body {
		flex: 1;
	}

	.edit-hint {
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.edit-grid {
		grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
	}
	.edit-tile {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md, 8px);
		padding: var(--space-3);
		cursor: grab;
	}
	.edit-tile-hidden {
		opacity: 0.5;
	}
	.drag-handle {
		color: var(--color-text-faint);
		touch-action: none;
		font-size: var(--text-lg);
		line-height: 1;
	}
	.edit-tile-title {
		flex: 1;
		font-size: var(--text-sm);
	}
	.visibility-toggle {
		display: flex;
		align-items: center;
		gap: var(--space-1);
		font-size: var(--text-xs);
		color: var(--color-text-muted);
		white-space: nowrap;
	}
	.edit-actions {
		display: flex;
		gap: var(--space-2);
		margin-top: var(--space-4);
	}
</style>
