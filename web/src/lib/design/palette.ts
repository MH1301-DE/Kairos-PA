import tokens from './kairos-tokens.json';

export type Theme = 'dark' | 'light';

export const colors = tokens.color;

// HR zones Z1..Z5: luminance rises monotonically so order survives grayscale
export function hrZoneColors(theme: Theme = 'dark'): string[] {
	const z = tokens.chart['hr-zones'][theme];
	return [z.z1, z.z2, z.z3, z.z4, z.z5];
}

// always stacked in this order: deep, rem, light, awake
export function sleepStageColors(theme: Theme = 'dark') {
	return tokens.chart.sleep[theme];
}

export function heatColors(theme: Theme = 'dark'): string[] {
	const h = tokens.chart.heat[theme];
	return [h['0'], h['1'], h['2'], h['3'], h['4']];
}

// ECharts theme: single series stay gray, color is reserved for categories
export function echartsTheme(theme: Theme = 'dark') {
	const c = tokens.color[theme];
	const axis = {
		axisLine: { show: false, lineStyle: { color: c['line-subtle'] } },
		axisTick: { show: false },
		axisLabel: { color: c['text-faint'], fontSize: 12 },
		splitLine: { lineStyle: { color: c['surface-raised'] } }
	};
	return {
		backgroundColor: 'transparent',
		textStyle: {
			fontFamily: tokens.font.family.sans,
			color: c['text-muted']
		},
		color: [c['data-primary'], c['data-secondary'], ...hrZoneColors(theme)],
		categoryAxis: axis,
		valueAxis: axis,
		timeAxis: axis,
		line: { lineStyle: { width: 2 }, symbol: 'none', connectNulls: false },
		tooltip: {
			backgroundColor: c['surface-raised'],
			borderWidth: 0,
			extraCssText: `border-radius:12px;box-shadow:${tokens.shadow[theme].overlay}`,
			textStyle: { color: c.text, fontSize: 12 }
		},
		bar: { itemStyle: { color: c['data-primary'], borderRadius: [4, 4, 0, 0] } },
		gauge: {
			title: { color: c['text-muted'] },
			detail: { color: c.text, fontWeight: 300 },
			axisLabel: { color: c['text-faint'] },
			axisTick: { show: false },
			splitLine: { show: false },
			pointer: { itemStyle: { color: c.text } }
		}
	};
}
