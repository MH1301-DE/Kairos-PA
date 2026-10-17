import type { Actions, PageServerLoad } from './$types';
import { redirect } from '@sveltejs/kit';
import { apiGet, ApiError } from '$lib/api';
import type { SchedulerAction } from '$lib/scheduler';
import { saveJob } from '$lib/schedulerSave';

export const load: PageServerLoad = async ({ fetch, url }) => {
	try {
		const { actions, default_timezone } = await apiGet<{
			actions: SchedulerAction[];
			default_timezone: string;
		}>(fetch, '/api/scheduler/actions');
		const template = url.searchParams.get('template');
		return {
			actions,
			defaultTimezone: default_timezone,
			template: template ? Number(template) : null
		};
	} catch (err) {
		if (err instanceof ApiError && err.status === 401) redirect(302, '/auth/login');
		throw err;
	}
};

export const actions: Actions = {
	save: async ({ request, fetch }) => saveJob(request, fetch, null)
};
