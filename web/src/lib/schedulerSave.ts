import { fail, redirect } from '@sveltejs/kit';
import { apiPost, apiPut } from '$lib/api';

// shared "save" form action of /scheduler/new and /scheduler/[id]
export async function saveJob(request: Request, fetchFn: typeof fetch, jobId: string | null) {
	const raw = String((await request.formData()).get('payload') ?? '');
	let body: unknown;
	try {
		body = JSON.parse(raw);
	} catch {
		return fail(400, { errors: { jobs: 'Formular konnte nicht gelesen werden.' } });
	}
	const { status, data } = jobId
		? await apiPut<{ detail?: unknown }>(fetchFn, `/api/scheduler/jobs/${jobId}`, body)
		: await apiPost<{ detail?: unknown }>(fetchFn, '/api/scheduler/jobs', body);
	if (status === 401) redirect(302, '/auth/login');
	if (status === 422) {
		const detail = data.detail as { errors?: Record<string, string> } | undefined;
		return fail(422, { errors: detail?.errors ?? { jobs: 'Ungültige Eingabe.' } });
	}
	if (status !== 200 && status !== 201) {
		return fail(status, { errors: { jobs: `Speichern fehlgeschlagen (${status}).` } });
	}
	redirect(303, '/scheduler');
}
