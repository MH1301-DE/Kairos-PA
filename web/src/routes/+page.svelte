<!-- web/src/routes/+page.svelte -->
<script lang="ts">
	import { invalidate } from '$app/navigation';
	import { untrack } from 'svelte';
	import MetricTile from '$lib/components/MetricTile.svelte';
	import { moduleById } from '$lib/modules';
	import { mergeTileAsOf, type TileState } from '$lib/dashboardTiles';
	import type { MetricResult } from '$lib/types';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();

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
</script>

<div class="dashboard-header">
	<h1>Dashboard</h1>
	<button type="button" class="btn btn-secondary" onclick={refreshAll} disabled={refreshing}>
		{refreshing ? 'Aktualisiert …' : '↻ Aktualisieren'}
	</button>
</div>

<div class="tile-grid">
	{#each tiles as tile (tile.moduleId)}
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
					<div class="tile tile-loading"><p>Lädt …</p></div>
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

<style>
	.dashboard-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-4);
		margin-bottom: var(--space-4);
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
		flex: 1;
		align-items: center;
		justify-content: center;
		min-height: 320px;
		color: var(--color-text-muted);
	}
</style>
