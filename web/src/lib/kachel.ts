import type { MetricResult } from './types';
import type { GaugeSpec, ModuleDef } from './modules';

// the five tile states from the design; every state keeps title row and height
export type KachelState = 'ok' | 'teilweise' | 'laden' | 'leer' | 'fehler';

export interface TileInput {
	loading: boolean;
	result: MetricResult | null;
	error: string | null;
}

export function kachelState(tile: TileInput, module: ModuleDef): KachelState {
	if (tile.loading) return 'laden';
	const r = tile.result;
	if (!r) return 'fehler';
	if (r.confidence === 'insufficient_data' || r.value === null) return 'leer';
	// the zone variant returns an all-zero dict instead of null on days without HR data
	if (module.kind === 'histogramm' && r.coverage_days === 0) return 'leer';
	if (r.coverage_days < r.coverage_required_days) return 'teilweise';
	if (r.confidence === 'low' || r.confidence === 'medium') return 'teilweise';
	return 'ok';
}

function unitWord(module: ModuleDef, n: number, dative = false): string {
	if (module.coverageUnit === 'Nächte') return n === 1 ? 'Nacht' : dative ? 'Nächten' : 'Nächte';
	return n === 1 ? 'Tag' : dative ? 'Tagen' : 'Tage';
}

// gaps are named in words in the footer, never smoothed over
export function coverageFoot(r: MetricResult, module: ModuleDef, state: KachelState): string {
	const have = r.coverage_days;
	const need = r.coverage_required_days;
	if (state === 'teilweise') {
		if (have < need) return `Ø aus ${have} von ${need} ${unitWord(module, need, true)}`;
		return `aus ${have} ${unitWord(module, have, true)} · Aussagekraft eingeschränkt`;
	}
	if (have === need && need > 1) return `alle ${need} ${unitWord(module, need)} vorhanden`;
	return `aus ${have} ${unitWord(module, have, true)}`;
}

export function formatDuration(seconds: number): string {
	const minutes = Math.floor(seconds / 60);
	return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, '0')}`;
}

export function formatNumber(v: number, decimals = 1): string {
	return v.toLocaleString('de-DE', {
		minimumFractionDigits: decimals,
		maximumFractionDigits: decimals
	});
}

// dial geometry from the design: 240° sweep starting at 150°, center (60, 60)
const START = 150;
const SWEEP = 240;

function point(radius: number, angle: number): string {
	const t = (angle * Math.PI) / 180;
	return `${(60 + radius * Math.cos(t)).toFixed(2)} ${(60 + radius * Math.sin(t)).toFixed(2)}`;
}

function arc(radius: number, a0: number, a1: number): string {
	const large = a1 - a0 > 180 ? 1 : 0;
	return `M${point(radius, a0)} A${radius} ${radius} 0 ${large} 1 ${point(radius, a1)}`;
}

export interface GaugeGeometry {
	track: string;
	value: string | null;
	band: string | null;
	fraction: number;
}

export function gaugeGeometry(spec: GaugeSpec, value: number): GaugeGeometry {
	const span = spec.max - spec.min;
	const frac = (v: number) => Math.min(1, Math.max(0, span > 0 ? (v - spec.min) / span : 0));
	const angle = (f: number) => START + SWEEP * f;
	const fraction = frac(value);
	const normal = spec.bands.find((b) => b.normal);
	return {
		track: arc(46, START, START + SWEEP),
		// a zero-length arc renders as a stray dot with round caps
		value: fraction > 0.005 ? arc(46, START, angle(fraction)) : null,
		band: normal ? arc(55, angle(frac(normal.from)), angle(frac(normal.to))) : null,
		fraction
	};
}
