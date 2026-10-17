import type { Actions, PageServerLoad } from './$types';
import { redirect, fail } from '@sveltejs/kit';
import { apiDelete, apiGet, apiPost, ApiError } from '$lib/api';
import type { ChatMessage, Conversation } from '$lib/types';

export const load: PageServerLoad = async ({ fetch, url, depends }) => {
	depends('chat:conversations');
	const conversationId = url.searchParams.get('c');
	try {
		const { conversations } = await apiGet<{ conversations: Conversation[] }>(
			fetch,
			'/api/agent/conversations'
		);
		let messages: ChatMessage[] = [];
		let compactedThroughSeq: number | null = null;
		if (conversationId) {
			const result = await apiGet<{
				messages: ChatMessage[];
				compacted_through_seq?: number | null;
			}>(fetch, `/api/agent/conversations/${conversationId}/messages`);
			messages = result.messages;
			compactedThroughSeq = result.compacted_through_seq ?? null;
		}
		return { conversations, messages, compactedThroughSeq, activeConversationId: conversationId };
	} catch (err) {
		if (err instanceof ApiError && err.status === 401) redirect(302, '/auth/login');
		throw err;
	}
};

export const actions: Actions = {
	newConversation: async ({ fetch, request }) => {
		// a question handed over from a tile's "Dazu fragen" link survives the redirect
		const q = String((await request.formData()).get('q') ?? '').trim();
		const { status, data } = await apiPost<{ id: string; detail?: string }>(
			fetch,
			'/api/agent/conversations',
			{}
		);
		if (status === 401) redirect(302, '/auth/login');
		if (status !== 201) {
			return fail(status, { error: `Konversation konnte nicht angelegt werden (${status}).` });
		}
		redirect(303, q ? `/chat?c=${data.id}&q=${encodeURIComponent(q)}` : `/chat?c=${data.id}`);
	},

	// reuses the /memory page's delete endpoint -- the undo chip on a
	// remember()-triggered memory entry doesn't need its own tool/route
	forgetRemembered: async ({ request, fetch }) => {
		const form = await request.formData();
		const memoryId = String(form.get('memory_id') ?? '');
		const { status } = await apiDelete(fetch, `/api/memory/${memoryId}`);
		if (status === 401) redirect(302, '/auth/login');
		if (status !== 204) {
			return fail(status, { error: 'Eintrag konnte nicht rückgängig gemacht werden.' });
		}
		return { forgotten: memoryId };
	}
};
