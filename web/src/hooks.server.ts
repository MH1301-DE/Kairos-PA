import type { Handle } from '@sveltejs/kit';
import { redirect } from '@sveltejs/kit';

const PUBLIC_PATHS = ['/auth/login', '/auth/callback'];

export const handle: Handle = async ({ event, resolve }) => {
	const isPublic = PUBLIC_PATHS.some((p) => event.url.pathname.startsWith(p));
	const hasSession = event.cookies.get('session_id') !== undefined;
	if (!isPublic && !hasSession) {
		redirect(302, '/auth/login');
	}
	return resolve(event);
};
