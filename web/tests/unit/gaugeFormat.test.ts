import { describe, it, expect } from 'vitest';
import { gaugeAxisDecimals } from '../../src/lib/gaugeFormat';

describe('gaugeAxisDecimals', () => {
	it('uses 1 decimal for ACWR-like fixed ranges (0-2, 4 splits -> step 0.5)', () => {
		expect(gaugeAxisDecimals(0, 2, 4)).toBe(1);
	});

	it('uses 0 decimals for hrv_baseline-like wide per-user ranges (step > 1)', () => {
		// real case reported live: min=62.56, max=124.54 (baseline +/- stddev,
		// padded) produced overlapping multi-decimal axis labels before this fix
		expect(gaugeAxisDecimals(62.56, 124.54, 4)).toBe(0);
	});

	it('uses 2 decimals for a narrow sub-1 range', () => {
		expect(gaugeAxisDecimals(0, 0.2, 4)).toBe(2);
	});

	it('never produces duplicate rounded labels for a 0-2 range at any step size', () => {
		const min = 0;
		const max = 2;
		const splitNumber = 4;
		const decimals = gaugeAxisDecimals(min, max, splitNumber);
		const step = (max - min) / splitNumber;
		const labels = Array.from({ length: splitNumber + 1 }, (_, i) =>
			(min + i * step).toFixed(decimals)
		);
		expect(new Set(labels).size).toBe(labels.length);
	});
});
