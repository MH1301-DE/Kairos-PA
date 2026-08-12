<!-- web/src/lib/components/BarTile.svelte -->
<script lang="ts">
	import type { EChartsOption } from 'echarts';
	import type { MetricResult } from '../types';
	import type { ModuleDef } from '../modules';
	import EChartsBase from './EChartsBase.svelte';
	import ConfidenceBadge from './ConfidenceBadge.svelte';

	let { result, module }: { result: MetricResult; module: ModuleDef } = $props();

	let option = $derived.by((): EChartsOption | null => {
		if (result.value === null) return null;
		const dict = result.value as Record<string, number>;
		const zones = Object.keys(dict).sort();
		return {
			xAxis: { type: 'category', data: zones },
			yAxis: { type: 'value', name: 'Sekunden' },
			series: [{ type: 'bar', data: zones.map((z) => Math.round(dict[z])) }],
			tooltip: { trigger: 'axis' }
		};
	});
</script>

<div class="bar-tile">
	<h3>{module.title}</h3>
	{#if result.confidence === 'insufficient_data' || option === null}
		<p class="empty">Nicht genug Daten</p>
	{:else}
		<EChartsBase {option} renderer="svg" />
	{/if}
	<ConfidenceBadge confidence={result.confidence} />
</div>

<style>
	.bar-tile {
		border: 1px solid #e2e8f0;
		border-radius: 0.5rem;
		padding: 1rem;
	}
	.empty {
		color: #94a3b8;
	}
</style>
