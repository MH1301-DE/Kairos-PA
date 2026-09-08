<!-- web/src/routes/+page.svelte -->
<script lang="ts">
	import { invalidate } from '$app/navigation';
	import MetricTile from '$lib/components/MetricTile.svelte';
	import { moduleById } from '$lib/modules';
	import type { MetricResult } from '$lib/types';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();

	interface TileState {
		moduleId: string;
		result: MetricResult | null;
		error: string | null;
		asOf: string;
		loading: boolean;
	}

	function todayIso(): string {
		return new Date().toISOString().slice(0, 10);
	}

	// local, per-tile state (asOf override, latest fetched result) layered on
	// top of the server-loaded snapshot -- resynced whenever data.tiles
	// changes (i.e. after the "Aktualisieren" button re-runs load())
	let tiles = $state<TileState[]>([]);

	$effect(() => {
		tiles = data.tiles.map((t) => ({ ...t, asOf: todayIso(), loading: false }));
	});

	let refreshing = $state(false);

	async function refreshAll() {
		refreshing = true;
		await invalidate('dashboard:tiles');
		refreshing = false;
	}

	async function refetchTile(tile: TileState) {
		const module = moduleById(tile.moduleId);
		if (!module) return;
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
		align-items: center;
		justify-content: center;
		min-height: 6rem;
		color: var(--color-text-muted);
	}
</style>
