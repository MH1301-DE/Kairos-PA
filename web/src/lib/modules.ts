import type { MetricResult } from './types';

export type ChartForm = 'value' | 'bar' | 'gauge';

export interface ValueField {
	key: string;
	label: string;
	unit?: string;
}

export interface GaugeBand {
	from: number;
	to: number;
	color: string;
	label: string;
}

export interface GaugeSpec {
	min: number;
	max: number;
	valueKey: string;
	bands: GaugeBand[];
}

export interface ModuleDef {
	moduleId: string;
	variant: string;
	title: string;
	form: ChartForm;
	fields?: ValueField[];
	trendKey?: string;
	gauge?: (result: MetricResult) => GaugeSpec;
}

function acwrGauge(): GaugeSpec {
	return {
		min: 0,
		max: 2,
		valueKey: 'ratio',
		bands: [
			{ from: 0, to: 0.8, color: '#94a3b8', label: 'undertraining' },
			{ from: 0.8, to: 1.3, color: '#22c55e', label: 'sweet_spot' },
			{ from: 1.3, to: 1.5, color: '#f59e0b', label: 'caution' },
			{ from: 1.5, to: 2.0, color: '#ef4444', label: 'high_risk' }
		]
	};
}

function hrvBaselineGauge(result: MetricResult): GaugeSpec {
	const v = result.value as Record<string, number>;
	const low = v.baseline_low;
	const high = v.baseline_high;
	const pad = high - low;
	return {
		min: low - pad,
		max: high + pad,
		valueKey: 'today',
		bands: [
			{ from: low - pad, to: low, color: '#ef4444', label: 'low' },
			{ from: low, to: high, color: '#22c55e', label: 'normal' },
			{ from: high, to: high + pad, color: '#f59e0b', label: 'high' }
		]
	};
}

export const MODULES: ModuleDef[] = [
	{ moduleId: 'trimp', variant: 'edwards', title: 'Trainingsbelastung (TRIMP)', form: 'value' },
	{
		moduleId: 'hr_zone_distribution',
		variant: 'percent_max',
		title: 'HF-Zonenverteilung (heute)',
		form: 'bar'
	},
	{
		moduleId: 'training_load',
		variant: 'default',
		title: 'CTL / ATL / TSB',
		form: 'value',
		fields: [
			{ key: 'ctl', label: 'CTL (Fitness)' },
			{ key: 'atl', label: 'ATL (Ermüdung)' },
			{ key: 'tsb', label: 'TSB (Form)' }
		]
	},
	{
		moduleId: 'acwr',
		variant: 'default',
		title: 'Belastungsverhältnis (ACWR)',
		form: 'gauge',
		gauge: acwrGauge
	},
	{
		moduleId: 'monotony_strain',
		variant: 'default',
		title: 'Trainingsmonotonie',
		form: 'value',
		fields: [
			{ key: 'monotony', label: 'Monotonie' },
			{ key: 'strain', label: 'Strain' }
		]
	},
	{
		moduleId: 'hrv_baseline',
		variant: 'default',
		title: 'HRV-Baseline',
		form: 'gauge',
		gauge: hrvBaselineGauge
	},
	{
		moduleId: 'sleep_debt',
		variant: 'default',
		title: 'Schlafschuld',
		form: 'value',
		fields: undefined
	},
	{
		moduleId: 'resting_hr_trend',
		variant: 'default',
		title: 'Ruhepuls-Trend',
		form: 'value',
		fields: [
			{ key: 'recent_avg', label: '7-Tage-Ø', unit: 'bpm' },
			{ key: 'prior_avg', label: 'Vorherige 30 Tage-Ø', unit: 'bpm' }
		],
		trendKey: 'delta_bpm'
	}
];

export function moduleById(id: string): ModuleDef | undefined {
	return MODULES.find((m) => m.moduleId === id);
}
