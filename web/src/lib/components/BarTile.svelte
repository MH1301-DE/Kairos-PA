<!-- web/src/lib/components/BarTile.svelte -->
<script lang="ts">
	import type { EChartsOption } from 'echarts';
	import type { MetricResult } from '../types';
	import type { ModuleDef } from '../modules';
	import EChartsBase from './EChartsBase.svelte';
	import ConfidenceBadge from './ConfidenceBadge.svelte';

	let { result, module }: { result: MetricResult; module: ModuleDef } = $props();

	let option = $derived.by((): EChartsOption | null => {
		// coverage_days=0 means the zone-seconds bucket was empty for as_of (e.g. no
		// workout that day) -- the variant still returns a dict with every zone at 0.0
		// instead of null, so value===null alone doesn't catch this. Without this check
		// the chart renders axes/labels with every bar at zero height, which reads as
		// "broken" rather than "no data".
		if (result.value === null || result.coverage_days === 0) return null;
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

<div class="tile bar-tile">
	<h3>{module.title}</h3>
	{#if result.confidence === 'insufficient_data' || option === null}
		<p class="empty">Nicht genug Daten</p>
	{:else}
		<EChartsBase {option} renderer="svg" />
	{/if}
	<ConfidenceBadge confidence={result.confidence} />
</div>
