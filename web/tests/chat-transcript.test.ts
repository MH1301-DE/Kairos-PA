import { describe, it, expect } from 'vitest';
import { applyEvent, historyToItems, newAssistant, type Item } from '../src/lib/chat/transcript';
import type { ChatMessage } from '../src/lib/types';

function msg(partial: Partial<ChatMessage> & Pick<ChatMessage, 'id' | 'role'>): ChatMessage {
	return {
		content: null,
		tool_calls: null,
		tool_call_id: null,
		tool_name: null,
		created_at: '2026-10-06T07:00:00Z',
		...partial
	};
}

describe('historyToItems', () => {
	it('groups assistant text and render charts into one bubble per turn', () => {
		const items = historyToItems([
			msg({ id: 'u1', role: 'user', content: 'Wie ist mein HRV?' }),
			msg({ id: 'a1', role: 'assistant', content: null, tool_calls: [] }),
			msg({
				id: 't1',
				role: 'tool',
				tool_name: 'render',
				content: JSON.stringify({
					summary: 'ok',
					data: {
						component: 'Gauge',
						config: { title: 'HRV', unit: 'ms', value: 50, min: 0, max: 100 }
					},
					meta: {}
				})
			}),
			msg({ id: 't2', role: 'tool', tool_name: null, content: '{"summary":"x"}' }),
			msg({ id: 'a2', role: 'assistant', content: 'Dein HRV liegt bei 50 ms.' })
		]);
		expect(items.map((i) => i.kind)).toEqual(['user', 'assistant']);
		const bubble = items[1] as Extract<Item, { kind: 'assistant' }>;
		expect(bubble.blocks.map((b) => b.kind)).toEqual(['chart', 'text']);
	});

	it('skips a render row with a broken envelope', () => {
		const items = historyToItems([
			msg({ id: 't', role: 'tool', tool_name: 'render', content: 'nope' })
		]);
		expect(items).toEqual([]);
	});
});

describe('applyEvent', () => {
	it('streams tokens, shows tool status and splits text around a tool round', () => {
		const items: Item[] = [];
		const bubble = newAssistant();
		items.push(bubble);
		applyEvent(items, bubble, { type: 'token', data: { text: 'Ich ' } });
		applyEvent(items, bubble, { type: 'token', data: { text: 'schaue.' } });
		applyEvent(items, bubble, { type: 'tool_start', data: { id: 'c1', name: 'query_health' } });
		expect(bubble.status).toBe('Kennzahl abfragen …');
		applyEvent(items, bubble, {
			type: 'tool_end',
			data: { id: 'c1', name: 'query_health', summary: 's', ok: true }
		});
		expect(bubble.status).toBeNull();
		applyEvent(items, bubble, { type: 'token', data: { text: 'Fertig.' } });
		expect(bubble.blocks).toEqual([
			{ kind: 'text', text: 'Ich schaue.' },
			{ kind: 'text', text: 'Fertig.' }
		]);
	});

	it('tolerates tool_end without tool_start and resolves a matching proposal', () => {
		const items: Item[] = [];
		const bubble = newAssistant();
		applyEvent(items, bubble, {
			type: 'proposal',
			data: {
				tool_call_id: 'p1',
				tool_name: 'plan_propose',
				summary: 'Plan anlegen?',
				arguments: {}
			}
		});
		applyEvent(items, bubble, {
			type: 'tool_end',
			data: { id: 'p1', name: 'plan_propose', summary: 'Plan gespeichert.', ok: true }
		});
		expect(items[0]).toMatchObject({
			kind: 'proposal',
			state: 'resolved',
			outcome: 'Plan gespeichert.'
		});
	});

	it('adds render charts, memory chips and mapped errors', () => {
		const items: Item[] = [];
		const bubble = newAssistant();
		applyEvent(items, bubble, {
			type: 'render',
			data: { id: 'r', component: 'StatCard', config: { title: 'x', items: [] } }
		});
		applyEvent(items, bubble, {
			type: 'memory',
			data: { id: 'm1', content: 'Knie', expires_at: '2026-10-20' }
		});
		applyEvent(items, bubble, { type: 'error', data: { detail: 'llm_provider_error' } });
		expect(bubble.blocks[0]).toMatchObject({ kind: 'chart', component: 'StatCard' });
		expect(items[0]).toMatchObject({ kind: 'memory', id: 'm1', expiresAt: '2026-10-20' });
		expect(items[1]).toMatchObject({
			kind: 'error',
			text: 'Der KI-Anbieter ist gerade nicht erreichbar.'
		});
	});
});
