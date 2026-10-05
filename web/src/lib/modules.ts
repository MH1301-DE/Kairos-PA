import type { MetricResult } from './types';
import { colors } from './design/palette';

// normal range = data band; green is reserved for interaction, never "good"
const c = colors.dark;

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
	// one entry per line in the tile's info tooltip -- a leading "Name: " is
	// bolded automatically, so each sub-KPI (and the closing "Richtwerte" line)
	// gets its own readable line instead of one dense paragraph
	description: string[];
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
			{ from: 0, to: 0.8, color: c['data-track'], label: 'undertraining' },
			{ from: 0.8, to: 1.3, color: c['data-band'], label: 'sweet_spot' },
			{ from: 1.3, to: 1.5, color: c['status-attention-mark'], label: 'caution' },
			{ from: 1.5, to: 2.0, color: c['status-deviation-mark'], label: 'high_risk' }
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
			{ from: low - pad, to: low, color: c['status-deviation-mark'], label: 'low' },
			{ from: low, to: high, color: c['data-band'], label: 'normal' },
			{ from: high, to: high + pad, color: c['data-track'], label: 'high' }
		]
	};
}

export const MODULES: ModuleDef[] = [
	{
		moduleId: 'trimp',
		variant: 'edwards',
		title: 'Trainingsbelastung (TRIMP)',
		description: [
			'TRIMP: gewichtete Trainingszeit in den 5 Herzfrequenz-Zonen (Edwards-Methode) — Zone 5 zählt am stärksten. 0 an einem Ruhetag ist normal.',
			'Richtwerte je Einheit: niedrig < 50 · mittel 50–150 · hoch > 150'
		],
		form: 'value'
	},
	{
		moduleId: 'hr_zone_distribution',
		variant: 'percent_max',
		title: 'HF-Zonenverteilung (heute)',
		description: [
			'Zone 1 (50–60 % HFmax): sehr leicht, aktive Erholung',
			'Zone 2 (60–70 %): Grundlagenausdauer, locker',
			'Zone 3 (70–80 %): mittlere Intensität, Tempo',
			'Zone 4 (80–90 %): schwer, Schwellenbereich',
			'Zone 5 (90–100 %): maximal, kurze Intervalle',
			'Nur aus echten Trainingsaktivitäten des Tages, nicht aus dem ganztägigen Ruhepuls.'
		],
		form: 'bar'
	},
	{
		moduleId: 'training_load',
		variant: 'default',
		title: 'CTL / ATL / TSB',
		description: [
			'CTL (Fitness): 42-Tage-Schnitt deiner Trainingsbelastung — langfristige Form.',
			'ATL (Ermüdung): 7-Tage-Schnitt deiner Trainingsbelastung — akute Müdigkeit.',
			'TSB (Form): CTL minus ATL.',
			'Richtwerte TSB: niedrig < -20 (Ermüdungsrisiko) · mittel -10 bis 5 · hoch > 5 (frisch)'
		],
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
		description: [
			'ACWR: Belastung der letzten 7 Tage geteilt durch den 28-Tage-Schnitt (Acute:Chronic Workload Ratio).',
			'Richtwerte: niedrig < 0,8 (Untertraining) · mittel 0,8–1,3 (Sweet Spot) · hoch > 1,5 (Verletzungsrisiko)'
		],
		form: 'gauge',
		gauge: acwrGauge
	},
	{
		moduleId: 'monotony_strain',
		variant: 'default',
		title: 'Trainingsmonotonie',
		description: [
			'Monotonie: Ø Belastung der letzten 7 Tage geteilt durch deren Streuung — hoch heißt wenig Abwechslung zwischen harten und leichten Tagen.',
			'Strain: Gesamtbelastung mal Monotonie — Übertrainings-Risiko bei fehlender Erholung.',
			'Richtwerte Monotonie: niedrig < 1,5 · mittel 1,5–2,0 · hoch > 2,0'
		],
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
		description: [
			'HRV-Baseline: heutiger morgendlicher HRV-Wert vs. Mittelwert ± Standardabweichung der letzten 60 Nächte.',
			'Richtwerte: niedrig < Baseline−1 SD (evtl. unzureichende Erholung) · mittel im Band · hoch > Baseline+1 SD',
			'Braucht die heutige Nacht-Messung — die postet oft erst am Morgen.'
		],
		form: 'gauge',
		gauge: hrvBaselineGauge
	},
	{
		moduleId: 'sleep_debt',
		variant: 'default',
		title: 'Schlafschuld',
		description: [
			'Schlafschuld: Summe aus (Zielschlaf minus tatsächlicher Schlaf) der letzten 7 Nächte. Negative Werte heißen Schlafüberschuss.',
			'Richtwerte: niedrig < 2 h · mittel 2–5 h · hoch > 5 h (Handlungsbedarf)'
		],
		form: 'value',
		fields: undefined
	},
	{
		moduleId: 'resting_hr_trend',
		variant: 'default',
		title: 'Ruhepuls-Trend',
		description: [
			'7-Tage-Ø: aktueller Ruhepuls-Schnitt.',
			'Vorherige 30 Tage-Ø: Vergleichswert davor.',
			'Ein spürbarer Anstieg kann ein früher Hinweis auf Übertraining, Stress oder eine beginnende Erkältung sein.',
			'Richtwerte Anstieg: niedrig < 2 bpm (normal) · mittel 2–5 bpm · hoch > 5 bpm'
		],
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
