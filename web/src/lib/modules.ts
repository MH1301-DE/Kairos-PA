import type { MetricResult } from './types';

// which body the <Kachel> renders for a module (names follow the design file)
export type KachelKind = 'kennzahl' | 'gauge' | 'belastung' | 'histogramm';

export type Tone = 'neutral' | 'attention' | 'deviation';

export interface ModuleStatus {
	tone: Tone;
	text: string;
}

export interface ValueField {
	key: string;
	label: string;
	unit?: string;
}

export interface GaugeBand {
	from: number;
	to: number;
	label: string;
	tone: Tone;
	// the personal normal range drawn as the outer band arc
	normal?: boolean;
	text: string;
}

export interface GaugeSpec {
	min: number;
	max: number;
	valueKey: string;
	decimals: number;
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
	kind: KachelKind;
	// header right: the window the value is computed over
	period: string;
	// coverage_days counts nights for sleep-based metrics, days otherwise
	coverageUnit: 'Tage' | 'Nächte';
	unit?: string;
	decimals?: number;
	fields?: ValueField[];
	trendKey?: string;
	gauge?: (result: MetricResult) => GaugeSpec;
	status?: (result: MetricResult) => ModuleStatus | null;
	emptyHint: string;
	askPrompt: string;
}

const fmt = (v: number, decimals = 1) =>
	v.toLocaleString('de-DE', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });

function dict(result: MetricResult): Record<string, number> {
	return (result.value ?? {}) as Record<string, number>;
}

function acwrGauge(): GaugeSpec {
	return {
		min: 0,
		max: 2,
		valueKey: 'ratio',
		decimals: 2,
		bands: [
			{ from: 0, to: 0.8, label: 'undertraining', tone: 'neutral', text: 'unter dem Bereich' },
			{
				from: 0.8,
				to: 1.3,
				label: 'sweet_spot',
				tone: 'neutral',
				normal: true,
				text: 'im Zielbereich 0,8–1,3'
			},
			{ from: 1.3, to: 1.5, label: 'caution', tone: 'attention', text: 'erhöht' },
			{ from: 1.5, to: 2.0, label: 'high_risk', tone: 'deviation', text: 'deutlich erhöht' }
		]
	};
}

function hrvBaselineGauge(result: MetricResult): GaugeSpec {
	const v = dict(result);
	const low = v.baseline_low;
	const high = v.baseline_high;
	const pad = high - low;
	return {
		min: low - pad,
		max: high + pad,
		valueKey: 'today',
		decimals: 0,
		bands: [
			{ from: low - pad, to: low, label: 'low', tone: 'deviation', text: 'unter dem Band' },
			{
				from: low,
				to: high,
				label: 'normal',
				tone: 'neutral',
				normal: true,
				text: `im Normalbereich ${fmt(low, 0)}–${fmt(high, 0)}`
			},
			{ from: high, to: high + pad, label: 'high', tone: 'neutral', text: 'über dem Band' }
		]
	};
}

// value sits in the first band whose upper edge it doesn't exceed; clamps to the ends
export function gaugeBandFor(spec: GaugeSpec, value: number): GaugeBand {
	return spec.bands.find((b) => value <= b.to) ?? spec.bands[spec.bands.length - 1];
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
		kind: 'kennzahl',
		period: 'heute',
		coverageUnit: 'Tage',
		unit: 'TRIMP',
		decimals: 0,
		// a training load isn't good or bad, so this stays a plain description
		status: (r) => {
			const v = r.value as number;
			if (v === 0) return { tone: 'neutral', text: 'Ruhetag' };
			if (v < 50) return { tone: 'neutral', text: 'leichte Einheit' };
			if (v <= 150) return { tone: 'neutral', text: 'mittlere Einheit' };
			return { tone: 'neutral', text: 'harte Einheit' };
		},
		emptyHint: 'Der Wert entsteht aus Aktivitäten mit Herzfrequenz.',
		askPrompt: 'Wie ist meine Trainingsbelastung heute einzuordnen?'
	},
	{
		moduleId: 'hr_zone_distribution',
		variant: 'percent_max',
		title: 'HF-Zonenverteilung',
		description: [
			'Zone 1 (50–60 % HFmax): sehr leicht, aktive Erholung',
			'Zone 2 (60–70 %): Grundlagenausdauer, locker',
			'Zone 3 (70–80 %): mittlere Intensität, Tempo',
			'Zone 4 (80–90 %): schwer, Schwellenbereich',
			'Zone 5 (90–100 %): maximal, kurze Intervalle',
			'Nur aus echten Trainingsaktivitäten des Tages, nicht aus dem ganztägigen Ruhepuls.'
		],
		kind: 'histogramm',
		period: 'heute',
		coverageUnit: 'Tage',
		emptyHint: 'Heute noch keine Aktivität mit Pulsmessung. Ruhetage sind keine Lücke.',
		askPrompt: 'Wie verteilt sich mein Training heute auf die Herzfrequenzzonen?'
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
		kind: 'belastung',
		period: '42 Tage',
		coverageUnit: 'Tage',
		decimals: 0,
		fields: [
			{ key: 'ctl', label: 'Fitness' },
			{ key: 'atl', label: 'Ermüdung' },
			{ key: 'tsb', label: 'Form' }
		],
		status: (r) => {
			const tsb = dict(r).tsb;
			if (tsb === undefined) return null;
			if (tsb < -20) return { tone: 'deviation', text: 'Ermüdungsrisiko' };
			if (tsb < -10) return { tone: 'attention', text: 'leicht ermüdet' };
			if (tsb > 5) return { tone: 'neutral', text: 'frisch' };
			return { tone: 'neutral', text: 'ausgeglichen' };
		},
		emptyHint: 'Fitness und Ermüdung brauchen etwa zwei Wochen Aktivitäten.',
		askPrompt: 'Was sagen meine Fitness-, Ermüdungs- und Formwerte gerade?'
	},
	{
		moduleId: 'acwr',
		variant: 'default',
		title: 'Belastungsverhältnis (ACWR)',
		description: [
			'ACWR: Belastung der letzten 7 Tage geteilt durch den 28-Tage-Schnitt (Acute:Chronic Workload Ratio).',
			'Richtwerte: niedrig < 0,8 (Untertraining) · mittel 0,8–1,3 (Sweet Spot) · hoch > 1,5 (Verletzungsrisiko)'
		],
		kind: 'gauge',
		period: '7 zu 28 Tage',
		coverageUnit: 'Tage',
		gauge: acwrGauge,
		emptyHint: 'Das Verhältnis braucht mindestens eine Woche Aktivitäten.',
		askPrompt: 'Ist mein Belastungsverhältnis (ACWR) gerade unbedenklich?'
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
		kind: 'kennzahl',
		period: '7 Tage',
		coverageUnit: 'Tage',
		decimals: 2,
		fields: [
			{ key: 'monotony', label: 'Monotonie' },
			{ key: 'strain', label: 'Strain' }
		],
		status: (r) => {
			const m = dict(r).monotony;
			if (m === undefined) return null;
			if (m > 2) return { tone: 'deviation', text: 'monoton' };
			if (m >= 1.5) return { tone: 'attention', text: 'eher gleichförmig' };
			return { tone: 'neutral', text: 'abwechslungsreich' };
		},
		emptyHint: 'Die Monotonie braucht eine Woche mit Training an mehreren Tagen.',
		askPrompt: 'Ist mein Training gerade zu gleichförmig?'
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
		kind: 'gauge',
		period: 'letzte Nacht',
		coverageUnit: 'Nächte',
		unit: 'ms',
		gauge: hrvBaselineGauge,
		emptyHint:
			'Die Uhr misst HRV nur im Schlaf. Trag sie heute Nacht — morgen früh steht hier dein Wert.',
		askPrompt: 'Wie steht meine HRV im Vergleich zu meinem Normalbereich?'
	},
	{
		moduleId: 'sleep_debt',
		variant: 'default',
		title: 'Schlafschuld',
		description: [
			'Schlafschuld: Summe aus (Zielschlaf minus tatsächlicher Schlaf) der letzten 7 Nächte. Negative Werte heißen Schlafüberschuss.',
			'Richtwerte: niedrig < 2 h · mittel 2–5 h · hoch > 5 h (Handlungsbedarf)'
		],
		kind: 'kennzahl',
		period: '7 Nächte',
		coverageUnit: 'Nächte',
		unit: 'h',
		decimals: 1,
		status: (r) => {
			const v = r.value as number;
			if (v < 0) return { tone: 'neutral', text: 'Schlafüberschuss' };
			if (v > 5) return { tone: 'deviation', text: 'hohe Schlafschuld' };
			if (v >= 2) return { tone: 'attention', text: 'spürbare Schlafschuld' };
			return { tone: 'neutral', text: 'kaum Schlafschuld' };
		},
		emptyHint: 'Schlaf wird erfasst, wenn die Uhr nachts getragen wird.',
		askPrompt: 'Wie viel Schlaf fehlt mir diese Woche, und was hilft?'
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
		kind: 'kennzahl',
		period: '7 Tage',
		coverageUnit: 'Tage',
		decimals: 0,
		fields: [
			{ key: 'recent_avg', label: '7-Tage-Ø', unit: 'bpm' },
			{ key: 'prior_avg', label: '30 Tage davor', unit: 'bpm' }
		],
		trendKey: 'delta_bpm',
		status: (r) => {
			const d = dict(r).delta_bpm;
			if (d === undefined) return null;
			const delta = `${d > 0 ? '+' : d < 0 ? '−' : '±'}${fmt(Math.abs(d), 1)} bpm`;
			if (d > 5) return { tone: 'deviation', text: `deutlich erhöht · ${delta}` };
			if (d >= 2) return { tone: 'attention', text: `leicht erhöht · ${delta}` };
			return { tone: 'neutral', text: `im üblichen Bereich · ${delta}` };
		},
		emptyHint: 'Für einen Trend braucht es mehrere Wochen Ruhepuls-Messungen.',
		askPrompt: 'Wie entwickelt sich mein Ruhepuls?'
	}
];

export function moduleById(id: string): ModuleDef | undefined {
	return MODULES.find((m) => m.moduleId === id);
}
