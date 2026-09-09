import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import BarTile from '../../src/lib/components/BarTile.svelte';
import { moduleById } from '../../src/lib/modules';
import type { MetricResult } from '../../src/lib/types';

describe('BarTile', () => {
	it('renders the module title and an empty-state message when insufficient_data', () => {
		const result: MetricResult = {
			metric_id: 'hr_zone_distribution',
			variant: 'percent_max',
			value: null,
			unit: 'seconds',
			confidence: 'insufficient_data',
			coverage_days: 0,
			coverage_required_days: 1,
			as_of: '2026-08-11'
		};
		render(BarTile, { result, module: moduleById('hr_zone_distribution')! });
		expect(screen.getByText('Nicht genug Daten')).toBeTruthy();
	});

	it('renders an empty-state message when coverage_days is 0 even though value is a non-null all-zero dict', () => {
		// hr_zone_distribution's variant always returns a full zone dict (0.0 per
		// zone) instead of null when there's no HR data for as_of (e.g. no workout
		// that day) -- confidence is 'low', not 'insufficient_data', and value isn't
		// null, so coverage_days is the only reliable "no real data" signal. Without
		// checking it, this used to render a chart with every bar at zero height.
		const result: MetricResult = {
			metric_id: 'hr_zone_distribution',
			variant: 'percent_max',
			value: { zone_1: 0, zone_2: 0, zone_3: 0, zone_4: 0, zone_5: 0 },
			unit: 'seconds',
			confidence: 'low',
			coverage_days: 0,
			coverage_required_days: 1,
			as_of: '2026-08-11'
		};
		render(BarTile, { result, module: moduleById('hr_zone_distribution')! });
		expect(screen.getByText('Nicht genug Daten')).toBeTruthy();
	});

	it('renders a chart container when zone data is present', () => {
		const result: MetricResult = {
			metric_id: 'hr_zone_distribution',
			variant: 'percent_max',
			value: { zone_1: 600, zone_2: 300, zone_3: 0, zone_4: 0, zone_5: 0 },
			unit: 'seconds',
			confidence: 'high',
			coverage_days: 1,
			coverage_required_days: 1,
			as_of: '2026-08-11'
		};
		const { container } = render(BarTile, { result, module: moduleById('hr_zone_distribution')! });
		expect(container.querySelector('div[style*="height"]')).toBeTruthy();
	});
});
