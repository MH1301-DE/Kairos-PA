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
			// never echo the password back — it would land in the SSR'd HTML
			return { mfaRequired: true, email };
		}
		if (status === 401) {
			return { error: 'E-Mail oder Passwort falsch.', email };
		}
		if (status === 409) {
			return {
				error:
					'Es ist bereits ein anderes Garmin-Konto verbunden. Ein Kontowechsel wird nicht ' +
					'unterstützt, da bereits Gesundheitsdaten für das verbundene Konto gespeichert sind.',
				email
			};
		}
		if (status === 503) {
			return {
				error: 'Garmin ist gerade nicht erreichbar. Bitte später erneut versuchen.',
				email
			};
		}
		return { error: `Unerwarteter Fehler (${status}): ${data.detail ?? 'unbekannt'}` };
	}
};
