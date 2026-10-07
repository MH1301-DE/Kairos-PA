import type { EChartsOption } from 'echarts';

function unitSuffix(unit: unknown): string {
	return typeof unit === 'string' && unit ? ` ${unit}` : '';
}

function titleOf(config: Record<string, unknown>): EChartsOption['title'] {
	return {
		text: String(config.title ?? ''),
		left: 'center',
		textStyle: { fontSize: 13, color: '#eceef3', fontWeight: 500 }
	};
}

export function chartOption(
	component: string,
	config: Record<string, unknown>
): EChartsOption | null {
	const unit = unitSuffix(config.unit);
	if (component === 'TimeSeriesChart') {
		const points = (config.points ?? []) as { date: string; value: number }[];
		return {
			title: titleOf(config),
			grid: { left: 48, right: 16, top: 40, bottom: 32 },
			tooltip: { trigger: 'axis', valueFormatter: (v) => `${String(v)}${unit}` },
			xAxis: { type: 'category', data: points.map((p) => p.date) },
			yAxis: { type: 'value', scale: true },
			series: [{ type: 'line', data: points.map((p) => p.value), showSymbol: points.length < 40 }]
		};
	}
	if (component === 'BarChart') {
		const bars = (config.bars ?? []) as { label: string; value: number }[];
		return {
			title: titleOf(config),
			grid: { left: 48, right: 16, top: 40, bottom: 32 },
			tooltip: { trigger: 'axis', valueFormatter: (v) => `${String(v)}${unit}` },
			xAxis: { type: 'category', data: bars.map((b) => b.label) },
			yAxis: { type: 'value' },
			series: [{ type: 'bar', data: bars.map((b) => b.value) }]
		};
	}
	if (component === 'Gauge') {
		return {
			title: titleOf(config),
			series: [
				{
					type: 'gauge',
					min: Number(config.min ?? 0),
					max: Number(config.max ?? 100),
					center: ['50%', '60%'],
					progress: { show: true, width: 10 },
					axisLine: { lineStyle: { width: 10 } },
					detail: { formatter: `{value}${unit}`, fontSize: 18, offsetCenter: [0, '40%'] },
					data: [{ value: Number(config.value ?? 0) }]
				}
			]
		};
	}
	return null;
}
