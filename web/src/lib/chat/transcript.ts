import type { ChatMessage } from '$lib/types';
import type { ChatEvent } from './sse';

export type Block =
	| { kind: 'text'; text: string }
	| { kind: 'chart'; component: string; config: Record<string, unknown> };

export interface AssistantItem {
	kind: 'assistant';
	key: string;
	blocks: Block[];
	status: string | null;
	// next token starts a new text block (a tool round sat in between)
	breakText: boolean;
}

export interface ProposalItem {
	kind: 'proposal';
	key: string;
	toolCallId: string;
	summary: string;
	state: 'open' | 'busy' | 'resolved';
	outcome: string | null;
}

export type Item =
	| { kind: 'user'; key: string; text: string }
	| AssistantItem
	| {
			kind: 'memory';
			key: string;
			id: string;
			content: string;
			expiresAt: string | null;
			undone: boolean;
	  }
	| ProposalItem
	| { kind: 'error'; key: string; text: string };

export const TOOL_LABELS: Record<string, string> = {
	query_health: 'Kennzahl abfragen',
	analyze_records: 'Verlauf analysieren',
	query_calendar: 'Kalender prüfen',
	recall: 'Erinnerungen durchsuchen',
	remember: 'Merken',
	render: 'Diagramm erstellen',
	plan_propose: 'Plan entwerfen',
	plan_progress: 'Planfortschritt prüfen'
};

export const ERROR_TEXT: Record<string, string> = {
	no_llm_provider_configured: 'Kein LLM-Anbieter konfiguriert.',
	llm_provider_error: 'Der KI-Anbieter ist gerade nicht erreichbar.'
};

let seq = 0;
export function nextKey(): string {
	seq += 1;
	return `i${seq}`;
}

export function newAssistant(): AssistantItem {
	return { kind: 'assistant', key: nextKey(), blocks: [], status: null, breakText: false };
}

function parseRender(content: string | null): Block | null {
	try {
		const envelope = JSON.parse(content ?? '') as {
			data?: { component?: unknown; config?: unknown };
		};
		const component = envelope.data?.component;
		const config = envelope.data?.config;
		if (typeof component !== 'string' || !config || typeof config !== 'object') return null;
		return { kind: 'chart', component, config: config as Record<string, unknown> };
	} catch {
		return null;
	}
}

export function historyToItems(messages: ChatMessage[]): Item[] {
	const items: Item[] = [];
	const currentAssistant = (): AssistantItem => {
		const last = items[items.length - 1];
		if (last?.kind === 'assistant') return last;
		const created = newAssistant();
		items.push(created);
		return created;
	};
	for (const m of messages) {
		if (m.role === 'user') {
			items.push({ kind: 'user', key: m.id, text: m.content ?? '' });
		} else if (m.role === 'assistant' && m.content) {
			currentAssistant().blocks.push({ kind: 'text', text: m.content });
		} else if (m.role === 'tool' && m.tool_name === 'render') {
			const block = parseRender(m.content);
			if (block) currentAssistant().blocks.push(block);
		}
	}
	items.push(...pendingProposals(messages));
	return items;
}

// mirrors dispatcher.needs_confirmation (write/destructive tools except remember)
const CONFIRMATION_TOOLS = new Set([
	'propose_calendar_event',
	'delete_calendar_event',
	'plan_commit',
	'plan_adjust'
]);

function proposalSummary(name: string, rawArguments: string): string {
	let args: Record<string, unknown> = {};
	try {
		const parsed = JSON.parse(rawArguments) as unknown;
		if (parsed && typeof parsed === 'object') args = parsed as Record<string, unknown>;
	} catch {
		// broken arguments still get a generic card
	}
	if (name === 'propose_calendar_event' && args.summary) {
		return `Termin "${str(args.summary)}" anlegen: ${str(args.start_at)} – ${str(args.end_at)}`;
	}
	if (name === 'delete_calendar_event' && args.event_id) {
		return `Termin ${str(args.event_id)} löschen`;
	}
	return `${name} ausführen`;
}

// the backend closes open calls once the user writes again, so only calls after the last user message can still be pending
function pendingProposals(messages: ChatMessage[]): ProposalItem[] {
	const answered = new Set(messages.filter((m) => m.role === 'tool').map((m) => m.tool_call_id));
	let lastUser = -1;
	messages.forEach((m, i) => {
		if (m.role === 'user') lastUser = i;
	});
	const pending: ProposalItem[] = [];
	messages.slice(lastUser + 1).forEach((m) => {
		if (m.role !== 'assistant') return;
		for (const call of m.tool_calls ?? []) {
			if (!CONFIRMATION_TOOLS.has(call.name) || answered.has(call.id)) continue;
			pending.push({
				kind: 'proposal',
				key: nextKey(),
				toolCallId: call.id,
				summary: proposalSummary(call.name, call.arguments ?? ''),
				state: 'open',
				outcome: null
			});
		}
	});
	return pending;
}

function str(value: unknown): string {
	return typeof value === 'string' ? value : '';
}

// mutates items/bubble in place so Svelte state proxies passed in stay reactive
export function applyEvent(items: Item[], bubble: AssistantItem, ev: ChatEvent): void {
	const d = ev.data;
	switch (ev.type) {
		case 'token': {
			const last = bubble.blocks[bubble.blocks.length - 1];
			if (last?.kind === 'text' && !bubble.breakText) last.text += str(d.text);
			else bubble.blocks.push({ kind: 'text', text: str(d.text) });
			bubble.breakText = false;
			break;
		}
		case 'tool_start': {
			const name = str(d.name);
			bubble.status = `${TOOL_LABELS[name] ?? name} …`;
			bubble.breakText = true;
			break;
		}
		case 'tool_end': {
			bubble.status = null;
			bubble.breakText = true;
			const proposal = items.find(
				(i): i is ProposalItem => i.kind === 'proposal' && i.toolCallId === str(d.id)
			);
			if (proposal) {
				proposal.state = 'resolved';
				proposal.outcome = str(d.summary) || null;
			}
			break;
		}
		case 'render':
			if (typeof d.component === 'string' && d.config && typeof d.config === 'object') {
				bubble.blocks.push({
					kind: 'chart',
					component: d.component,
					config: d.config as Record<string, unknown>
				});
			}
			break;
		case 'memory':
			items.push({
				kind: 'memory',
				key: nextKey(),
				id: str(d.id),
				content: str(d.content),
				expiresAt: str(d.expires_at) || null,
				undone: false
			});
			break;
		case 'proposal':
			items.push({
				kind: 'proposal',
				key: nextKey(),
				toolCallId: str(d.tool_call_id),
				summary: str(d.summary),
				state: 'open',
				outcome: null
			});
			break;
		case 'error':
			items.push({
				kind: 'error',
				key: nextKey(),
				text: ERROR_TEXT[str(d.detail)] ?? 'Es ist ein Fehler aufgetreten.'
			});
			break;
	}
}
