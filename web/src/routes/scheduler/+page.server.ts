import type { Actions, PageServerLoad } from './$types';
import { fail, redirect } from '@sveltejs/kit';
import { apiDelete, apiGet, apiPatch, apiPost, ApiError } from '$lib/api';
import type { SchedulerJob } from '$lib/scheduler';

export const load: PageServerLoad = async ({ fetch, depends }) => {
	depends('scheduler:jobs');
	try {
		const { jobs } = await apiGet<{ jobs: SchedulerJob[] }>(fetch, '/api/scheduler/jobs');
		return { jobs };
	} catch (err) {
		if (err instanceof ApiError && err.status === 401) redirect(302, '/auth/login');
		throw err;
	}
};

export const actions: Actions = {
	toggle: async ({ request, fetch }) => {
		const form = await request.formData();
		const jobId = String(form.get('job_id'));
		const enabled = form.get('enabled') === 'true';
		const { status } = await apiPatch(fetch, `/api/scheduler/jobs/${jobId}`, { enabled });
		if (status !== 200)
			return fail(status, { jobId, error: 'Job konnte nicht umgeschaltet werden.' });
		return { jobId };
	},
	run: async ({ request, fetch }) => {
		const jobId = String((await request.formData()).get('job_id'));
		const { status } = await apiPost(fetch, `/api/scheduler/jobs/${jobId}/run`, {});
		if (status === 409) return fail(409, { jobId, error: 'Der Job läuft gerade schon.' });
		if (status !== 202) return fail(status, { jobId, error: 'Job konnte nicht gestartet werden.' });
		return { jobId, started: true };
	},
	remove: async ({ request, fetch }) => {
		const jobId = String((await request.formData()).get('job_id'));
		const { status } = await apiDelete(fetch, `/api/scheduler/jobs/${jobId}`);
		if (status === 409) {
			return fail(409, { jobId, error: 'Ein laufender Job kann nicht gelöscht werden.' });
		}
		if (status !== 204) return fail(status, { jobId, error: 'Job konnte nicht gelöscht werden.' });
		return { jobId, deleted: true };
	}
};
