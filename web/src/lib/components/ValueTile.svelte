<!-- web/src/lib/components/ValueTile.svelte -->
<script lang="ts">
	import type { MetricResult } from '../types';
	import type { ModuleDef } from '../modules';
	import ConfidenceBadge from './ConfidenceBadge.svelte';

	let { result, module }: { result: MetricResult; module: ModuleDef } = $props();
</script>

<div class="value-tile">
	<h3>{module.title}</h3>
	{#if result.confidence === 'insufficient_data' || result.value === null}
		<p class="empty">Nicht genug Daten</p>
	{:else if module.fields}
		{@const dict = result.value as Record<string, number>}
		<dl>
			{#each module.fields as field (field.key)}
				<dt>{field.label}</dt>
				<dd>{(dict[field.key] ?? 0).toFixed(2)} {field.unit ?? ''}</dd>
			{/each}
		</dl>
		{#if module.trendKey}
			{@const delta = dict[module.trendKey] ?? 0}
			<p class="trend">{delta < 0 ? '↓' : delta > 0 ? '↑' : '→'} {delta.toFixed(1)} bpm</p>
		{/if}
	{:else}
		<p class="scalar">{(result.value as number).toFixed(1)} {result.unit}</p>
	{/if}
	<ConfidenceBadge confidence={result.confidence} />
</div>

<style>
	.value-tile {
		border: 1px solid #e2e8f0;
		border-radius: 0.5rem;
		padding: 1rem;
	}
	.empty {
		color: #94a3b8;
	}
</style>
