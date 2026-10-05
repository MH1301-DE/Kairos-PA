import type { Actions, PageServerLoad } from './$types';
import { redirect, fail } from '@sveltejs/kit';
import { apiDelete, apiGet, apiPost, ApiError } from '$lib/api';
import type { ChatMessage, Conversation, MemoryEntry, Proposal, ToolResult } from '$lib/types';

export const load: PageServerLoad = async ({ fetch, url, depends }) => {
	depends('chat:conversations');
	const conversationId = url.searchParams.get('c');
	try {
		const { conversations } = await apiGet<{ conversations: Conversation[] }>(
			fetch,
			'/api/agent/conversations'
		);
		let messages: ChatMessage[] = [];
		if (conversationId) {
			const result = await apiGet<{ messages: ChatMessage[] }>(
				fetch,
				`/api/agent/conversations/${conversationId}/messages`
			);
			messages = result.messages;
		}
		return { conversations, messages, activeConversationId: conversationId };
	} catch (err) {
		if (err instanceof ApiError && err.status === 401) redirect(302, '/auth/login');
		throw err;
	}
};

export const actions: Actions = {
	newConversation: async ({ fetch }) => {
		const { status, data } = await apiPost<{ id: string; detail?: string }>(
			fetch,
			'/api/agent/conversations',
			{}
		);
		if (status === 401) redirect(302, '/auth/login');
		if (status !== 201) {
			return fail(status, { error: `Konversation konnte nicht angelegt werden (${status}).` });
		}
		redirect(303, `/chat?c=${data.id}`);
	},

	send: async ({ request, fetch }) => {
		const form = await request.formData();
		const conversationId = String(form.get('conversation_id') ?? '');
		const content = String(form.get('content') ?? '').trim();
		if (!content) {
			return fail(400, { error: 'Nachricht darf nicht leer sein.' });
		}
		const { status, data } = await apiPost<{
			reply: string | null;
			proposal: Proposal | null;
			remembered: MemoryEntry[];
			detail?: string;
		}>(fetch, `/api/agent/conversations/${conversationId}/messages`, { content });
		if (status === 401) redirect(302, '/auth/login');
		if (status !== 200) {
			return fail(status, { error: `Nachricht konnte nicht gesendet werden (${status}).` });
		}
		return { reply: data.reply, proposal: data.proposal, remembered: data.remembered };
	},

	confirm: async ({ request, fetch }) => {
		const form = await request.formData();
		const conversationId = String(form.get('conversation_id') ?? '');
		const toolCallId = String(form.get('tool_call_id') ?? '');
		const { status, data } = await apiPost<ToolResult & { detail?: string }>(
			fetch,
			`/api/agent/conversations/${conversationId}/proposals/${toolCallId}/confirm`,
			{}
		);
		if (status === 401) redirect(302, '/auth/login');
		if (status !== 200) {
			return fail(status, { error: `Aktion konnte nicht bestätigt werden (${status}).` });
		}
		return { confirmResult: data };
	},

	reject: async ({ request, fetch }) => {
		const form = await request.formData();
		const conversationId = String(form.get('conversation_id') ?? '');
		const toolCallId = String(form.get('tool_call_id') ?? '');
		const { status } = await apiPost(
			fetch,
			`/api/agent/conversations/${conversationId}/proposals/${toolCallId}/reject`,
			{}
		);
		if (status === 401) redirect(302, '/auth/login');
		if (status !== 200) {
			return fail(status, { error: `Aktion konnte nicht abgelehnt werden (${status}).` });
		}
		return { rejected: true };
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
