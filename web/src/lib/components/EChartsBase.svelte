<!-- web/src/lib/components/EChartsBase.svelte -->
<script lang="ts">
	import * as echarts from 'echarts';
	import type { EChartsOption } from 'echarts';

	let { option }: { option: EChartsOption } = $props();
	let container: HTMLDivElement;
	let chart: echarts.ECharts | undefined;

	$effect(() => {
		if (!chart) {
			chart = echarts.init(container);
		}
		chart.setOption(option, true);
		return () => {
			// no per-option teardown needed; chart instance is disposed below on unmount
		};
	});

	$effect(() => {
		return () => {
			chart?.dispose();
			chart = undefined;
		};
	});
</script>

<div bind:this={container} style="width: 100%; height: 220px;"></div>
