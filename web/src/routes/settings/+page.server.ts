import type { Actions, PageServerLoad } from './$types';
import { redirect } from '@sveltejs/kit';
import { apiGet, apiPut, ApiError } from '$lib/api';
import type { ProfileSettings } from '$lib/types';

export const load: PageServerLoad = async ({ fetch }) => {
	try {
		const profile = await apiGet<ProfileSettings>(fetch, '/api/settings/profile');
		return { profile };
	} catch (err) {
		if (err instanceof ApiError && err.status === 401) redirect(302, '/auth/login');
		throw err;
	}
};

function optionalNumber(raw: FormDataEntryValue | null): number | null {
	const value = typeof raw === 'string' ? raw.trim() : '';
	return value ? Number(value) : null;
}

export const actions: Actions = {
	save: async ({ request, fetch }) => {
		const form = await request.formData();
		const birthDate = ((form.get('birth_date') as string) ?? '').trim();
		const { status } = await apiPut<{ detail?: unknown }>(fetch, '/api/settings/profile', {
			birth_date: birthDate || null,
			hr_max_override: optionalNumber(form.get('hr_max_override')),
			resting_hr_override: optionalNumber(form.get('resting_hr_override'))
		});
		if (status === 422) {
			return {
				saveError:
					'Ungültige Eingabe: HFmax 120–230 bpm, Ruhepuls 30–100 bpm, Geburtsdatum in der Vergangenheit (ab 1900).'
			};
		}
		if (status !== 200) {
			return { saveError: `Einstellungen konnten nicht gespeichert werden (${status}).` };
		}
		return { saved: true };
	}
};
