import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async ({ cookies }) => {
	// hooks.server.ts already guarantees a session cookie exists on every
	// non-public route reachable here; we don't decode it (opaque to the
	// frontend, backend owns session state) — just confirm presence for the nav.
	return { authenticated: cookies.get('session_id') !== undefined };
};
