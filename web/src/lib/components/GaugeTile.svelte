<!-- web/src/lib/components/GaugeTile.svelte -->
<script lang="ts">
	import type { EChartsOption } from 'echarts';
	import type { MetricResult } from '../types';
	import type { ModuleDef } from '../modules';
	import EChartsBase from './EChartsBase.svelte';
	import ConfidenceBadge from './ConfidenceBadge.svelte';

	let { result, module }: { result: MetricResult; module: ModuleDef } = $props();

	let option = $derived.by((): EChartsOption | null => {
		if (result.value === null || !module.gauge) return null;
		const spec = module.gauge(result);
		// a zero-width band (e.g. a flat baseline) would make every color stop NaN
		if (spec.max === spec.min) return null;
		const dict = result.value as Record<string, number>;
		const value = dict[spec.valueKey];
		return {
			series: [
				{
					type: 'gauge',
					min: spec.min,
					max: spec.max,
					axisLine: {
						lineStyle: {
							width: 12,
							color: spec.bands.map((b) => [(b.to - spec.min) / (spec.max - spec.min), b.color])
						}
					},
					pointer: { show: true },
					detail: { formatter: `{value}`, fontSize: 20 },
					data: [{ value: Math.round(value * 100) / 100 }]
				}
			]
		};
	});
</script>

<div class="tile gauge-tile">
	<h3>{module.title}</h3>
	{#if result.confidence === 'insufficient_data' || option === null}
		<p class="empty">Nicht genug Daten</p>
	{:else}
		<EChartsBase {option} renderer="svg" />
	{/if}
	<ConfidenceBadge confidence={result.confidence} />
</div>
