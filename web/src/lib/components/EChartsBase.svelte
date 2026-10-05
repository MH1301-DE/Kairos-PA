<!-- web/src/lib/components/EChartsBase.svelte -->
<script lang="ts">
	import * as echarts from 'echarts';
	import type { EChartsOption } from 'echarts';
	import { echartsTheme } from '../design/palette';

	// registered once per module load; built from kairos-tokens.json
	echarts.registerTheme('kairos', echartsTheme('dark'));

	let { option, renderer = 'canvas' }: { option: EChartsOption; renderer?: 'canvas' | 'svg' } =
		$props();
	let container: HTMLDivElement;
	let chart: echarts.ECharts | undefined;
	let resizeObserver: ResizeObserver | undefined;

	$effect(() => {
		if (!chart) {
			chart = echarts.init(container, 'kairos', { renderer });
			// the dashboard grid reflows on resize/rotation; echarts needs to be told
			resizeObserver = new ResizeObserver(() => chart?.resize());
			resizeObserver.observe(container);
		}
		chart.setOption(option, true);
	});

	$effect(() => {
		return () => {
			resizeObserver?.disconnect();
			resizeObserver = undefined;
			chart?.dispose();
			chart = undefined;
		};
	});
</script>

<div bind:this={container} style="width: 100%; height: 220px;"></div>
