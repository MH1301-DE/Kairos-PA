import type { Actions, PageServerLoad } from './$types';
import { error, redirect } from '@sveltejs/kit';
import { apiGet, ApiError } from '$lib/api';
import type { SchedulerAction, SchedulerJob } from '$lib/scheduler';
import { saveJob } from '$lib/schedulerSave';

export const load: PageServerLoad = async ({ fetch, params }) => {
	try {
		const [{ actions, default_timezone }, job] = await Promise.all([
			apiGet<{ actions: SchedulerAction[]; default_timezone: string }>(
				fetch,
				'/api/scheduler/actions'
			),
			apiGet<SchedulerJob>(fetch, `/api/scheduler/jobs/${params.id}`)
		]);
		return { actions, defaultTimezone: default_timezone, job };
	} catch (err) {
		if (err instanceof ApiError && err.status === 401) redirect(302, '/auth/login');
		if (err instanceof ApiError && err.status === 404) error(404, 'Job nicht gefunden');
		throw err;
	}
};

export const actions: Actions = {
	save: async ({ request, fetch, params }) => saveJob(request, fetch, params.id)
};
