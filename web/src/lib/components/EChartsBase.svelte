<!-- web/src/lib/components/EChartsBase.svelte -->
<script lang="ts">
	import * as echarts from 'echarts';
	import type { EChartsOption } from 'echarts';

	// registered once per module load; mirrors the tokens in app.css so charts
	// sit on the dark tile surface instead of assuming ECharts' light default
	echarts.registerTheme('kairos', {
		backgroundColor: 'transparent',
		textStyle: { fontFamily: 'Inter, system-ui, sans-serif', color: '#9096ac' },
		color: ['#e8935a', '#6bbf8c', '#e0b155', '#ef6461'],
		categoryAxis: {
			axisLine: { lineStyle: { color: '#333849' } },
			axisTick: { lineStyle: { color: '#333849' } },
			axisLabel: { color: '#9096ac' },
			splitLine: { lineStyle: { color: '#262a35' } }
		},
		valueAxis: {
			axisLine: { lineStyle: { color: '#333849' } },
			axisTick: { lineStyle: { color: '#333849' } },
			axisLabel: { color: '#9096ac' },
			splitLine: { lineStyle: { color: '#262a35' } }
		},
		tooltip: {
			backgroundColor: '#1c1f28',
			borderColor: '#333849',
			textStyle: { color: '#eceef3' }
		},
		bar: { itemStyle: { color: '#e8935a', borderRadius: [4, 4, 0, 0] } },
		gauge: { title: { color: '#9096ac' }, detail: { color: '#eceef3' } }
	});

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
