import type { Actions, PageServerLoad } from './$types';
import { fail, redirect } from '@sveltejs/kit';
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

const RANGE_ERROR =
	'Ungültige Eingabe: HFmax 120–230 bpm, Ruhepuls 30–100 bpm, Geburtsdatum in der Vergangenheit (ab 1900).';

// undefined = not a number; null = empty field, which clears the value
function optionalNumber(raw: FormDataEntryValue | null): number | null | undefined {
	const value = typeof raw === 'string' ? raw.trim() : '';
	if (!value) return null;
	const parsed = Number(value);
	return Number.isFinite(parsed) ? parsed : undefined;
}

export const actions: Actions = {
	save: async ({ request, fetch }) => {
		const form = await request.formData();
		const birthDate = ((form.get('birth_date') as string | null) ?? '').trim();
		const hrMax = optionalNumber(form.get('hr_max_override'));
		const restingHr = optionalNumber(form.get('resting_hr_override'));
		if (hrMax === undefined || restingHr === undefined) {
			return fail(422, { saveError: RANGE_ERROR });
		}
		const { status } = await apiPut<{ detail?: unknown }>(fetch, '/api/settings/profile', {
			birth_date: birthDate || null,
			hr_max_override: hrMax,
			resting_hr_override: restingHr
		});
		if (status === 401) redirect(302, '/auth/login');
		if (status === 422) return fail(422, { saveError: RANGE_ERROR });
		if (status !== 200) {
			return fail(status, {
				saveError: `Einstellungen konnten nicht gespeichert werden (${status}).`
			});
		}
		return { saved: true };
	}
};
