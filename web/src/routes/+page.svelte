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
	// eslint-disable-next-line svelte/prefer-svelte-reactivity -- deliberately not reactive, see above
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

	// only shown tiles take part in drag-and-drop; hidden ones live in the library
	let shownItems = $derived(editItems.filter((i) => i.visible));
	let hiddenItems = $derived(editItems.filter((i) => !i.visible));

	function handleDndConsider(e: CustomEvent<{ items: EditItem[] }>) {
		editItems = [...e.detail.items, ...hiddenItems];
	}
	function handleDndFinalize(e: CustomEvent<{ items: EditItem[] }>) {
		editItems = [...e.detail.items, ...hiddenItems];
	}

	function hideItem(id: string) {
		editItems = editItems.map((i) => (i.id === id ? { ...i, visible: false } : i));
	}
	function showItem(id: string) {
		const item = editItems.find((i) => i.id === id);
		if (!item) return;
		editItems = [
			...shownItems,
			{ ...item, visible: true },
			...hiddenItems.filter((i) => i.id !== id)
		];
	}

	function layoutPayload(): string {
		return JSON.stringify(
			editItems.map((item, i) => ({ module_id: item.id, position: i, visible: item.visible }))
		);
	}

	let garminExpired = $derived(
		data.connections.some((c) => c.connector === 'garmin' && c.status === 'reauth_required')
	);
</script>

<div class="dashboard-header">
	<h1>Übersicht</h1>
	<div class="header-actions">
		{#if editMode}
			<button type="button" class="btn btn-ghost" onclick={() => (editMode = false)}>
				Abbrechen
			</button>
			<button type="submit" form="layout-form" class="btn btn-primary" disabled={savingLayout}>
				{savingLayout ? 'Speichert …' : 'Fertig'}
			</button>
		{:else}
			<button type="button" class="btn btn-ghost" onclick={enterEditMode}>Anordnen</button>
			<button type="button" class="btn btn-secondary" onclick={refreshAll} disabled={refreshing}>
				{refreshing ? 'Wird abgeglichen …' : 'Aktualisieren'}
			</button>
		{/if}
	</div>
</div>

{#snippet metricTile(tile: TileState, editing: boolean, onremove?: () => void)}
	{@const module = moduleById(tile.moduleId)}
	{#if module}
		<MetricTile
			{tile}
			{module}
			asOf={tile.asOf}
			today={todayIso()}
			{garminExpired}
			{editing}
			{onremove}
			onretry={() => refetchTile(tile)}
			onasof={(date) => {
				tile.asOf = date;
				refetchTile(tile);
			}}
		/>
	{/if}
{/snippet}

{#if editMode}
	<form
		id="layout-form"
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
	</form>
	<p class="edit-hint">Ziehen zum Anordnen, × zum Entfernen.</p>
	<div
		class="tile-grid"
		use:dndzone={{ items: shownItems, flipDurationMs: 200 }}
		onconsider={handleDndConsider}
		onfinalize={handleDndFinalize}
	>
		{#each shownItems as item (item.id)}
			{@const tile = tiles.find((t) => t.moduleId === item.id)}
			<div class="tile-slot" animate:flip={{ duration: 200 }}>
				{#if tile}{@render metricTile(tile, true, () => hideItem(item.id))}{/if}
			</div>
		{/each}
	</div>
	{#if form?.layoutError}
		<p class="status-error">{form.layoutError}</p>
	{/if}
	<section class="library">
		<h2>Kachelbibliothek</h2>
		{#if hiddenItems.length === 0}
			<p class="t-caption">Alle Kacheln sind auf der Übersicht.</p>
		{:else}
			<div class="library-items">
				{#each hiddenItems as item (item.id)}
					<button type="button" class="btn btn-secondary" onclick={() => showItem(item.id)}>
						+ {moduleById(item.id)?.title ?? item.id}
					</button>
				{/each}
			</div>
		{/if}
	</section>
{:else}
	<div class="tile-grid">
		{#each visibleTiles as tile (tile.moduleId)}
			<div class="tile-slot">{@render metricTile(tile, false)}</div>
		{/each}
	</div>
{/if}

<style>
	.dashboard-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-4);
		margin-bottom: var(--space-6);
	}
	.dashboard-header h1 {
		margin: 0;
	}
	.header-actions {
		display: flex;
		gap: var(--space-2);
	}
	.tile-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(min(100%, 340px), 1fr));
		gap: var(--space-5);
	}
	.tile-slot {
		min-width: 0;
	}
	.edit-hint {
		color: var(--text-muted);
		font: var(--type-caption);
	}
	.library {
		margin-top: var(--space-10);
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.library h2 {
		margin: 0;
	}
	.library-items {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}
</style>
