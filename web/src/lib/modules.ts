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
	description: string;
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
	{
		moduleId: 'trimp',
		variant: 'edwards',
		title: 'Trainingsbelastung (TRIMP)',
		description:
			'Edwards-TRIMP: die Zeit in jeder Herzfrequenz-Zone (1–5) wird gewichtet ' +
			'(Zone 5 zählt am stärksten) und aufsummiert. Höher = intensiveres oder ' +
			'längeres Training an diesem Tag. 0 an einem Ruhetag ist normal.',
		form: 'value'
	},
	{
		moduleId: 'hr_zone_distribution',
		variant: 'percent_max',
		title: 'HF-Zonenverteilung (heute)',
		description:
			'Sekunden in jeder der 5 Herzfrequenz-Zonen (bezogen auf deine geschätzte ' +
			'maximale Herzfrequenz) — nur aus echten Trainingsaktivitäten des Tages, ' +
			'nicht aus dem ganztägigen Ruhepuls. Ohne Training an diesem Tag leer.',
		form: 'bar'
	},
	{
		moduleId: 'training_load',
		variant: 'default',
		title: 'CTL / ATL / TSB',
		description:
			'Banister-Modell: CTL (Fitness) ist ein 42-Tage-gleitender Schnitt deiner ' +
			'Trainingsbelastung, ATL (Ermüdung) ein 7-Tage-Schnitt. TSB (Form) = CTL − ATL — ' +
			'positiv heißt ausgeruht, stark negativ heißt hohe Ermüdung.',
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
		description:
			'Acute:Chronic Workload Ratio — Belastung der letzten 7 Tage geteilt durch den ' +
			'28-Tage-Schnitt. 0,8–1,3 gilt als Sweet Spot; über 1,5 als erhöhtes ' +
			'Verletzungsrisiko durch zu schnellen Belastungsanstieg.',
		form: 'gauge',
		gauge: acwrGauge
	},
	{
		moduleId: 'monotony_strain',
		variant: 'default',
		title: 'Trainingsmonotonie',
		description:
			'Monotonie = Ø Belastung der letzten 7 Tage geteilt durch deren Streuung — hohe ' +
			'Werte heißen wenig Abwechslung zwischen harten und leichten Tagen. ' +
			'Strain = Gesamtbelastung × Monotonie, ein Maß für Übertrainings-Risiko.',
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
		description:
			'Vergleicht deinen heutigen morgendlichen HRV-Wert mit Mittelwert ± ' +
			'Standardabweichung der letzten 60 Nächte. Deutlich unter der Baseline kann auf ' +
			'unzureichende Erholung hindeuten. Braucht die heutige Nacht-Messung — die postet ' +
			'oft erst am Morgen.',
		form: 'gauge',
		gauge: hrvBaselineGauge
	},
	{
		moduleId: 'sleep_debt',
		variant: 'default',
		title: 'Schlafschuld',
		description:
			'Summe aus (Zielschlaf − tatsächlicher Schlaf) der letzten 7 Nächte. Negative ' +
			'Werte bedeuten Schlafüberschuss, positive Werte ein Defizit gegenüber deinem ' +
			'eingestellten Schlafziel.',
		form: 'value',
		fields: undefined
	},
	{
		moduleId: 'resting_hr_trend',
		variant: 'default',
		title: 'Ruhepuls-Trend',
		description:
			'Vergleicht den Ruhepuls-Schnitt der letzten 7 Tage mit dem Schnitt der ' +
			'vorherigen 30 Tage. Ein spürbarer Anstieg kann ein früher Hinweis auf ' +
			'Übertraining, Stress oder eine beginnende Erkältung sein.',
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
