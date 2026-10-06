import { describe, it, expect } from 'vitest';
import { chartOption } from '../src/lib/chat/chartOption';

type Loose = Record<string, unknown> & {
	xAxis: { data: unknown[] };
	series: { type: string; data: unknown[]; min?: number; max?: number }[];
};

describe('chartOption', () => {
	it('maps a TimeSeriesChart to a line series over dates', () => {
		const opt = chartOption('TimeSeriesChart', {
			title: 'HRV',
			unit: 'ms',
			points: [{ date: '2026-10-01', value: 50 }]
		}) as unknown as Loose;
		expect(opt.xAxis.data).toEqual(['2026-10-01']);
		expect(opt.series[0].data).toEqual([50]);
	});

	it('maps a BarChart to a bar series', () => {
		const opt = chartOption('BarChart', {
			title: 'Schlaf',
			unit: 'h',
			bars: [{ label: 'Mo', value: 7 }]
		}) as unknown as Loose;
		expect(opt.xAxis.data).toEqual(['Mo']);
		expect(opt.series[0].type).toBe('bar');
		expect(opt.series[0].data).toEqual([7]);
	});

	it('maps a Gauge to a gauge series with min and max', () => {
		const opt = chartOption('Gauge', {
			title: 'ACWR',
			unit: '',
			value: 1.1,
			min: 0,
			max: 2
		}) as unknown as Loose;
		expect(opt.series[0].type).toBe('gauge');
		expect(opt.series[0].min).toBe(0);
		expect(opt.series[0].max).toBe(2);
	});

	it('returns null for HTML-rendered components', () => {
		expect(chartOption('StatCard', { title: 'x', items: [] })).toBeNull();
		expect(chartOption('Table', { title: 'x', columns: [], rows: [] })).toBeNull();
		expect(chartOption('Unknown', {})).toBeNull();
	});
});
