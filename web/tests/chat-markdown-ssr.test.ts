// @vitest-environment node
import { describe, it, expect } from 'vitest';
import { render } from 'svelte/server';
import Markdown from '../src/lib/chat/Markdown.svelte';
import ChatThread from '../src/lib/chat/ChatThread.svelte';
import type { ChatMessage } from '../src/lib/types';

describe('Markdown SSR', () => {
	it('renders escaped plain text on the server without DOMPurify', () => {
		const { body } = render(Markdown, {
			props: { text: '**fett** <script>alert(1)</script>' }
		});
		expect(body).not.toContain('<script>');
		expect(body).toContain('&lt;script>');
		expect(body).toContain('**fett**');
	});

	it('server-renders a thread with assistant markdown, a chart and a pending proposal', () => {
		const base = { tool_calls: null, tool_call_id: null, tool_name: null, created_at: '' };
		const messages: ChatMessage[] = [
			{ ...base, id: 'u1', role: 'user', content: 'Hallo' },
			{
				...base,
				id: 'a1',
				role: 'assistant',
				content: '**Hier** <script>x</script>',
				tool_calls: [{ id: 'c1', name: 'plan_commit', arguments: '{"plan_id":"p"}' }]
			},
			{
				...base,
				id: 't1',
				role: 'tool',
				tool_name: 'render',
				content: JSON.stringify({
					summary: 'ok',
					data: { component: 'StatCard', config: { title: 'Heute', items: [] } },
					meta: {}
				})
			}
		];
		const { body } = render(ChatThread, { props: { conversationId: 'c', messages } });
		expect(body).not.toContain('<script>');
		expect(body).toContain('Heute');
		expect(body).toContain('plan_commit ausführen');
		expect(body).toContain('Bestätigen');
	});
});
