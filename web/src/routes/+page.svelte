<!-- web/src/routes/+page.svelte -->
<script lang="ts">
	import MetricTile from '$lib/components/MetricTile.svelte';
	import { moduleById } from '$lib/modules';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();
</script>

<h1>Dashboard</h1>
<div class="tile-grid">
	{#each data.tiles as tile (tile.moduleId)}
		{@const module = moduleById(tile.moduleId)}
		{#if module && tile.result}
			<MetricTile result={tile.result} {module} />
		{:else if module}
			<div class="tile-error">
				<h3>{module.title}</h3>
				<p>{tile.error}</p>
			</div>
		{/if}
	{/each}
</div>

<style>
	.tile-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
		gap: var(--space-4);
	}
</style>
