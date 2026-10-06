import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import MetricTile from '../../src/lib/components/MetricTile.svelte';
import { moduleById } from '../../src/lib/modules';
import type { MetricResult } from '../../src/lib/types';

const TODAY = '2026-10-05';

function result(overrides: Partial<MetricResult> = {}): MetricResult {
	return {
		metric_id: 'sleep_debt',
		variant: 'default',
		value: 3.2,
		unit: 'hours',
		confidence: 'high',
		coverage_days: 7,
		coverage_required_days: 7,
		as_of: TODAY,
		...overrides
	};
}

function renderTile(moduleId: string, r: MetricResult | null, extra: Record<string, unknown> = {}) {
	return render(MetricTile, {
		tile: { loading: false, result: r, error: r ? null : 'x' },
		module: moduleById(moduleId)!,
		asOf: TODAY,
		today: TODAY,
		...extra
	});
}

describe('MetricTile', () => {
	it('shows a scalar with unit, status line, coverage footer and ask link', () => {
		renderTile('sleep_debt', result());
		expect(screen.getByText('3,2')).toBeTruthy();
		expect(screen.getByText('spürbare Schlafschuld')).toBeTruthy();
		expect(screen.getByText('alle 7 Nächte vorhanden')).toBeTruthy();
		const ask = screen.getByText('Dazu fragen →') as HTMLAnchorElement;
		expect(ask.getAttribute('href')).toContain('/chat?q=');
	});

	it('marks a partial tile by naming the basis in the footer', () => {
		const { container } = renderTile('sleep_debt', result({ coverage_days: 4 }));
		expect(screen.getByText('Ø aus 4 von 7 Nächten').classList.contains('partial')).toBe(true);
		expect(container.querySelector('[data-state="teilweise"]')).toBeTruthy();
	});

	it('renders the empty state with the module hint and progress', () => {
		renderTile(
			'hrv_baseline',
			result({
				metric_id: 'hrv_baseline',
				value: null,
				confidence: 'insufficient_data',
				coverage_days: 3,
				coverage_required_days: 14
			})
		);
		expect(screen.getByText('Noch nicht genug Daten')).toBeTruthy();
		expect(screen.getByText(/Bisher: 3 von 14 Nächten/)).toBeTruthy();
		expect(screen.getByText('Jetzt abgleichen')).toBeTruthy();
	});

	it('leaves out the progress line when history is enough but today is missing', () => {
		renderTile(
			'hrv_baseline',
			result({
				metric_id: 'hrv_baseline',
				value: null,
				confidence: 'insufficient_data',
				coverage_days: 32,
				coverage_required_days: 20
			})
		);
		expect(screen.queryByText(/Bisher:/)).toBeNull();
	});

	it('offers a retry on a fetch error', async () => {
		const onretry = vi.fn();
		renderTile('sleep_debt', null, { onretry });
		expect(screen.getByText('Daten gerade nicht verfügbar')).toBeTruthy();
		await fireEvent.click(screen.getByText('Erneut versuchen'));
		expect(onretry).toHaveBeenCalledOnce();
	});

	it('sends the user to re-login when Garmin access expired', () => {
		renderTile('sleep_debt', null, { garminExpired: true });
		expect(screen.getByText('Garmin braucht eine neue Anmeldung')).toBeTruthy();
		expect(screen.getByText('Bei Garmin anmelden').getAttribute('href')).toContain('/onboarding');
	});

	it('keeps the title row while loading and shows no values', () => {
		const { container } = render(MetricTile, {
			tile: { loading: true, result: result(), error: null },
			module: moduleById('sleep_debt')!,
			asOf: TODAY,
			today: TODAY
		});
		expect(container.querySelector('[aria-busy="true"]')).toBeTruthy();
		expect(screen.queryByText('3,2')).toBeNull();
	});

	it('draws a gauge with the band status for ACWR', () => {
		const { container } = renderTile(
			'acwr',
			result({ metric_id: 'acwr', value: { ratio: 1.42 }, coverage_days: 28 })
		);
		expect(screen.getByText('1,42')).toBeTruthy();
		expect(screen.getByText('erhöht').classList.contains('attention')).toBe(true);
		expect(container.querySelector('svg path.band')).toBeTruthy();
	});

	it('lists HR zones with h:mm and total time', () => {
		renderTile(
			'hr_zone_distribution',
			result({
				metric_id: 'hr_zone_distribution',
				value: { zone_1: 1800, zone_2: 1200, zone_3: 0, zone_4: 0, zone_5: 0 },
				coverage_days: 1,
				coverage_required_days: 1
			})
		);
		expect(screen.getByText('0:50')).toBeTruthy();
		expect(screen.getByText('0:30')).toBeTruthy();
		expect(screen.getByText('Z5')).toBeTruthy();
	});

	it('treats a zone dict without HR coverage as empty, not as a chart of zeros', () => {
		renderTile(
			'hr_zone_distribution',
			result({
				metric_id: 'hr_zone_distribution',
				value: { zone_1: 0, zone_2: 0, zone_3: 0, zone_4: 0, zone_5: 0 },
				confidence: 'low',
				coverage_days: 0,
				coverage_required_days: 1
			})
		);
		expect(screen.getByText('Noch nicht genug Daten')).toBeTruthy();
	});

	it('shows fitness, fatigue and form with the TSB status', () => {
		renderTile(
			'training_load',
			result({
				metric_id: 'training_load',
				value: { ctl: 48, atl: 55, tsb: -7 },
				coverage_days: 90,
				coverage_required_days: 90
			})
		);
		expect(screen.getByText('Fitness')).toBeTruthy();
		expect(screen.getByText('−7')).toBeTruthy();
		expect(screen.getByText('ausgeglichen')).toBeTruthy();
	});

	it('labels a pinned earlier date instead of the period', () => {
		render(MetricTile, {
			tile: { loading: false, result: result(), error: null },
			module: moduleById('sleep_debt')!,
			asOf: '2026-10-01',
			today: TODAY
		});
		expect(screen.getByText('Stand 1.10.2026')).toBeTruthy();
	});

	it('shows the edit layer with a remove control and hides the ask link', async () => {
		const onremove = vi.fn();
		renderTile('sleep_debt', result(), { editing: true, onremove });
		expect(screen.queryByText('Dazu fragen →')).toBeNull();
		await fireEvent.click(screen.getByLabelText('Schlafschuld entfernen'));
		expect(onremove).toHaveBeenCalledOnce();
	});
});
