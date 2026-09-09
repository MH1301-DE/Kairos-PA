import { describe, it, expect } from 'vitest';
import { MODULES, moduleById } from '../../src/lib/modules';

describe('module registry', () => {
	it('has exactly 8 modules, one per known metric_id', () => {
		const ids = MODULES.map((m) => m.moduleId);
		expect(ids).toEqual([
			'trimp',
			'hr_zone_distribution',
			'training_load',
			'acwr',
			'monotony_strain',
			'hrv_baseline',
			'sleep_debt',
			'resting_hr_trend'
		]);
	});

	it('every module has a unique moduleId', () => {
		const ids = MODULES.map((m) => m.moduleId);
		expect(new Set(ids).size).toBe(ids.length);
	});

	it('every module has a non-empty description, one non-empty line each, for the tile info tooltip', () => {
		for (const m of MODULES) {
			expect(m.description.length).toBeGreaterThan(0);
			for (const line of m.description) {
				expect(line.trim().length).toBeGreaterThan(0);
			}
		}
	});

	it('moduleById finds a known module and returns undefined for unknown', () => {
		expect(moduleById('trimp')?.title).toBe('Trainingsbelastung (TRIMP)');
		expect(moduleById('nonexistent')).toBeUndefined();
	});

	it('acwr gauge spec maps a mid-range ratio into the sweet_spot band', () => {
		const acwr = moduleById('acwr')!;
		const spec = acwr.gauge!({
			metric_id: 'acwr',
			variant: 'default',
			value: { ratio: 1.0 },
			unit: 'ratio',
			confidence: 'high',
			coverage_days: 28,
			coverage_required_days: 7,
			as_of: '2026-08-11'
		});
		expect(spec.valueKey).toBe('ratio');
		const sweetSpot = spec.bands.find((b) => b.label === 'sweet_spot');
		expect(sweetSpot).toBeDefined();
		expect(1.0).toBeGreaterThanOrEqual(sweetSpot!.from);
		expect(1.0).toBeLessThanOrEqual(sweetSpot!.to);
	});
});
