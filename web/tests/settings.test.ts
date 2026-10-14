import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import SettingsPage from '../src/routes/settings/+page.svelte';
import type { ProfileSettings } from '../src/lib/types';

function profile(overrides: Partial<ProfileSettings> = {}): ProfileSettings {
	return {
		birth_date: '1990-05-01',
		hr_max_override: 214,
		resting_hr_override: 48,
		hr_max_used: 214,
		hr_max_source: 'eingetragen',
		hr_max_measured_12m: 219,
		hr_max_warning: 'gemessen 219 bpm, eingetragen 214 – prüfen',
		...overrides
	};
}

const LAYOUT = { authenticated: true, connections: [], jobs: [] };

describe('settings page', () => {
	it('renders the stored values and the warning', () => {
		render(SettingsPage, { data: { ...LAYOUT, profile: profile() }, form: null });
		expect((screen.getByLabelText(/Geburtsdatum/) as HTMLInputElement).value).toBe('1990-05-01');
		expect((screen.getByLabelText(/Gemessene HFmax/) as HTMLInputElement).value).toBe('214');
		expect((screen.getByLabelText(/Ruhepuls/) as HTMLInputElement).value).toBe('48');
		expect(screen.getByText('214 bpm')).toBeTruthy();
		expect(screen.getByText('(eingetragen)')).toBeTruthy();
		expect(screen.getByText('gemessen 219 bpm, eingetragen 214 – prüfen')).toBeTruthy();
	});

	it('says that HFmax is missing when nothing is set', () => {
		render(SettingsPage, {
			data: {
				...LAYOUT,
				profile: profile({
					birth_date: null,
					hr_max_override: null,
					resting_hr_override: null,
					hr_max_used: null,
					hr_max_source: null,
					hr_max_measured_12m: null,
					hr_max_warning: null
				})
			},
			form: null
		});
		expect(screen.getByText(/HFmax fehlt/)).toBeTruthy();
		expect(screen.queryByText(/prüfen/)).toBeNull();
	});
});
