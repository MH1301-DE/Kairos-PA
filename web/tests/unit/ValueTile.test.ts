import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import ValueTile from '../../src/lib/components/ValueTile.svelte';
import { moduleById } from '../../src/lib/modules';
import type { MetricResult } from '../../src/lib/types';

describe('ValueTile', () => {
	it('renders a scalar value with its unit', () => {
		const result: MetricResult = {
			metric_id: 'trimp',
			variant: 'edwards',
			value: 42.5,
			unit: 'trimp_pt',
			confidence: 'high',
			coverage_days: 1,
			coverage_required_days: 1,
			as_of: '2026-08-11'
		};
		render(ValueTile, { result, module: moduleById('trimp')! });
		expect(screen.getByText(/42.5/).textContent).toContain('trimp_pt');
	});

	it('renders "Nicht genug Daten" for insufficient_data', () => {
		const result: MetricResult = {
			metric_id: 'trimp',
			variant: 'edwards',
			value: null,
			unit: 'trimp_pt',
			confidence: 'insufficient_data',
			coverage_days: 0,
			coverage_required_days: 1,
			as_of: '2026-08-11'
		};
		render(ValueTile, { result, module: moduleById('trimp')! });
		expect(screen.getByText('Nicht genug Daten')).toBeTruthy();
	});

	it('renders multi-field dict values with their labels', () => {
		const result: MetricResult = {
			metric_id: 'training_load',
			variant: 'default',
			value: { ctl: 15.2, atl: 9.3, tsb: 5.9 },
			unit: 'ctl_atl_tsb',
			confidence: 'high',
			coverage_days: 81,
			coverage_required_days: 90,
			as_of: '2026-08-11'
		};
		render(ValueTile, { result, module: moduleById('training_load')! });
		expect(screen.getByText(/CTL \(Fitness\)/)).toBeTruthy();
		expect(screen.getByText(/15.2/)).toBeTruthy();
	});
});
