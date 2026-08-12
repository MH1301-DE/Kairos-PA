import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import GaugeTile from '../../src/lib/components/GaugeTile.svelte';
import { moduleById } from '../../src/lib/modules';
import type { MetricResult } from '../../src/lib/types';

describe('GaugeTile', () => {
	it('renders the empty state for insufficient_data', () => {
		const result: MetricResult = {
			metric_id: 'acwr',
			variant: 'default',
			value: null,
			unit: 'ratio',
			confidence: 'insufficient_data',
			coverage_days: 2,
			coverage_required_days: 7,
			as_of: '2026-08-11'
		};
		render(GaugeTile, { result, module: moduleById('acwr')! });
		expect(screen.getByText('Nicht genug Daten')).toBeTruthy();
	});

	it('renders a chart container when a ratio is present', () => {
		const result: MetricResult = {
			metric_id: 'acwr',
			variant: 'default',
			value: { ratio: 1.1 },
			unit: 'ratio',
			confidence: 'high',
			coverage_days: 28,
			coverage_required_days: 7,
			as_of: '2026-08-11'
		};
		const { container } = render(GaugeTile, { result, module: moduleById('acwr')! });
		expect(container.querySelector('div[style*="height"]')).toBeTruthy();
	});
});
