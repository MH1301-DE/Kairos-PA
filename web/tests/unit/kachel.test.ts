import { describe, expect, it } from 'vitest';
import { kachelState, coverageFoot, gaugeGeometry, formatDuration } from '../../src/lib/kachel';
import { moduleById, gaugeBandFor } from '../../src/lib/modules';
import type { MetricResult } from '../../src/lib/types';

function result(overrides: Partial<MetricResult> = {}): MetricResult {
	return {
		metric_id: 'sleep_debt',
		variant: 'default',
		value: 3.2,
		unit: 'hours',
		confidence: 'high',
		coverage_days: 7,
		coverage_required_days: 7,
		as_of: '2026-10-05',
		...overrides
	};
}

const sleep = moduleById('sleep_debt')!;
const zones = moduleById('hr_zone_distribution')!;

describe('kachelState', () => {
	it('is "laden" while loading, regardless of an old result', () => {
		expect(kachelState({ loading: true, result: result(), error: null }, sleep)).toBe('laden');
	});

	it('is "fehler" without a result', () => {
		expect(kachelState({ loading: false, result: null, error: 'x' }, sleep)).toBe('fehler');
	});

	it('is "leer" for insufficient data or a null value', () => {
		const r1 = result({ confidence: 'insufficient_data' });
		const r2 = result({ value: null });
		expect(kachelState({ loading: false, result: r1, error: null }, sleep)).toBe('leer');
		expect(kachelState({ loading: false, result: r2, error: null }, sleep)).toBe('leer');
	});

	it('is "leer" for a zone histogram without any HR coverage, even with an all-zero dict', () => {
		const r = result({
			metric_id: 'hr_zone_distribution',
			value: { zone_1: 0, zone_2: 0 },
			confidence: 'low',
			coverage_days: 0,
			coverage_required_days: 1
		});
		expect(kachelState({ loading: false, result: r, error: null }, zones)).toBe('leer');
	});

	it('is "teilweise" when coverage is below what the metric needs', () => {
		const r = result({ coverage_days: 4 });
		expect(kachelState({ loading: false, result: r, error: null }, sleep)).toBe('teilweise');
	});

	it('is "teilweise" when the backend reports low or medium confidence', () => {
		const r = result({ confidence: 'medium' });
		expect(kachelState({ loading: false, result: r, error: null }, sleep)).toBe('teilweise');
	});

	it('is "ok" for a one-day metric with a real value but no activity that day', () => {
		const trimp = moduleById('trimp')!;
		const r = result({ metric_id: 'trimp', value: 0, coverage_days: 0, coverage_required_days: 1 });
		expect(kachelState({ loading: false, result: r, error: null }, trimp)).toBe('ok');
	});

	it('is "ok" with full coverage and high confidence', () => {
		expect(kachelState({ loading: false, result: result(), error: null }, sleep)).toBe('ok');
	});
});

describe('coverageFoot', () => {
	it('names the basis in words when partial', () => {
		expect(coverageFoot(result({ coverage_days: 4 }), sleep, 'teilweise')).toBe(
			'Ø aus 4 von 7 Nächten'
		);
	});

	it('says everything is there when complete', () => {
		expect(coverageFoot(result(), sleep, 'ok')).toBe('alle 7 Nächte vorhanden');
	});

	it('uses the singular for a one-day metric', () => {
		const trimp = moduleById('trimp')!;
		const r = result({ coverage_days: 1, coverage_required_days: 1 });
		expect(coverageFoot(r, trimp, 'ok')).toBe('aus 1 Tag');
	});

	it('says there was no activity instead of "0 von 1"', () => {
		const trimp = moduleById('trimp')!;
		const r = result({ value: 0, coverage_days: 0, coverage_required_days: 1 });
		expect(coverageFoot(r, trimp, 'ok')).toBe('keine Aktivität im Zeitraum');
	});

	it('reports the longer basis when coverage exceeds the minimum', () => {
		const acwr = moduleById('acwr')!;
		const r = result({ coverage_days: 28, coverage_required_days: 7 });
		expect(coverageFoot(r, acwr, 'ok')).toBe('aus 28 Tagen');
	});
});

describe('gauge', () => {
	const acwr = moduleById('acwr')!;
	const spec = acwr.gauge!(result({ value: { ratio: 1 } }));

	it('picks the band that contains the value and clamps outside values', () => {
		expect(gaugeBandFor(spec, 1.0).label).toBe('sweet_spot');
		expect(gaugeBandFor(spec, 1.4).tone).toBe('attention');
		expect(gaugeBandFor(spec, 9).label).toBe('high_risk');
		expect(gaugeBandFor(spec, -1).label).toBe('undertraining');
	});

	it('draws the value arc proportionally inside the 240° sweep', () => {
		const g = gaugeGeometry(spec, 1);
		expect(g.fraction).toBeCloseTo(0.5);
		expect(g.track.startsWith('M')).toBe(true);
		expect(g.band).not.toBeNull();
	});

	it('clamps the value fraction to the dial', () => {
		expect(gaugeGeometry(spec, 5).fraction).toBe(1);
		expect(gaugeGeometry(spec, -5).fraction).toBe(0);
	});
});

describe('formatDuration', () => {
	it('formats seconds as h:mm', () => {
		expect(formatDuration(0)).toBe('0:00');
		expect(formatDuration(3 * 60)).toBe('0:03');
		expect(formatDuration(5 * 3600 + 22 * 60 + 40)).toBe('5:22');
	});
});
