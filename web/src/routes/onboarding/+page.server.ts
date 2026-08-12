import type { Actions } from './$types';
import { apiPost } from '$lib/api';

export const actions: Actions = {
	default: async ({ request, fetch }) => {
		const form = await request.formData();
		const email = form.get('email') as string;
		const password = form.get('password') as string;
		const mfaToken = (form.get('mfa_token') as string) || null;

		const { status, data } = await apiPost<{ status?: string; detail?: string }>(
			fetch,
			'/api/connections/garmin',
			{ email, password, mfa_token: mfaToken }
		);

		if (status === 201) {
			return { success: true, email };
		}
		if (status === 202) {
			return { mfaRequired: true, email, password };
		}
		if (status === 401) {
			return { error: 'E-Mail oder Passwort falsch.' };
		}
		if (status === 503) {
			return { error: 'Garmin ist gerade nicht erreichbar. Bitte später erneut versuchen.' };
		}
		return { error: `Unerwarteter Fehler (${status}): ${data.detail ?? 'unbekannt'}` };
	}
};
