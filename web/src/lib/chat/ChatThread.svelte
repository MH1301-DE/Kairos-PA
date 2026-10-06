<script lang="ts">
	import { untrack } from 'svelte';
	import { enhance } from '$app/forms';
	import { invalidate } from '$app/navigation';
	import { ApiError } from '$lib/api';
	import type { ChatMessage } from '$lib/types';
	import ChatChart from './ChatChart.svelte';
	import Markdown from './Markdown.svelte';
	import { postStream } from './sse';
	import {
		applyEvent,
		historyToItems,
		newAssistant,
		nextKey,
		type AssistantItem,
		type Item,
		type ProposalItem
	} from './transcript';

	let { conversationId, messages }: { conversationId: string; messages: ChatMessage[] } = $props();

	// history is captured once; the parent remounts this component per conversation
	let items = $state<Item[]>(untrack(() => historyToItems(messages)));
	let draft = $state('');
	let sending = $state(false);

	const SEND_ERRORS: Record<number, string> = {
		404: 'Konversation nicht gefunden – bitte die Seite neu laden.'
	};
	const PROPOSAL_ERRORS: Record<number, string> = {
		404: 'Vorschlag nicht gefunden – bitte die Seite neu laden.',
		409: 'Dieser Vorschlag wurde bereits bearbeitet.'
	};

	function formatDate(value: string): string {
		const date = new Date(value);
		return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString('de-DE');
	}

	function pushError(text: string) {
		items.push({ kind: 'error', key: nextKey(), text });
	}

	// returns the HTTP status when the request was refused before streaming
	async function runStream(
		path: string,
		body: unknown,
		errorTexts: Record<number, string>
	): Promise<number | null> {
		sending = true;
		items.push(newAssistant());
		const bubble = items[items.length - 1] as AssistantItem;
		let sawDone = false;
		let refusedStatus: number | null = null;
		let failed = false;
		try {
			for await (const ev of await postStream(path, body)) {
				if (ev.type === 'done') sawDone = true;
				else applyEvent(items, bubble, ev);
			}
		} catch (err) {
			failed = true;
			if (err instanceof ApiError && err.status === 401) {
				window.location.href = '/auth/login';
				return err.status;
			}
			const status = err instanceof ApiError ? err.status : 0;
			if (status) refusedStatus = status;
			pushError(errorTexts[status] ?? 'Die Anfrage ist fehlgeschlagen.');
		}
		bubble.status = null;
		if (!sawDone && !failed) pushError('Die Verbindung wurde unterbrochen.');
		sending = false;
		// the first message sets the conversation title server-side
		if (sawDone) await invalidate('chat:conversations');
		return refusedStatus;
	}

	async function send(event: SubmitEvent) {
		event.preventDefault();
		const content = draft.trim();
		if (!content || sending) return;
		draft = '';
		// the backend closes unanswered proposals as soon as the user writes again
		for (const item of items) {
			if (item.kind === 'proposal' && item.state === 'open') item.state = 'resolved';
		}
		items.push({ kind: 'user', key: nextKey(), text: content });
		await runStream(`/api/agent/conversations/${conversationId}/stream`, { content }, SEND_ERRORS);
	}

	async function resolveProposal(proposal: ProposalItem, action: 'confirm' | 'reject') {
		if (sending || proposal.state !== 'open') return;
		proposal.state = 'busy';
		const refused = await runStream(
			`/api/agent/conversations/${conversationId}/proposals/${encodeURIComponent(proposal.toolCallId)}/${action}`,
			undefined,
			PROPOSAL_ERRORS
		);
		if (proposal.state === 'busy') proposal.state = refused === 409 ? 'resolved' : 'open';
	}

	function isEmptyBubble(item: AssistantItem): boolean {
		return item.blocks.length === 0 && item.status === null;
	}
</script>

<div class="message-list">
	{#each items as item, index (item.key)}
		{#if item.kind === 'user'}
			<div class="message message-user">{item.text}</div>
		{:else if item.kind === 'assistant'}
			{#if !isEmptyBubble(item)}
				<div class="message message-assistant">
					{#each item.blocks as block, i (i)}
						{#if block.kind === 'text'}
							<Markdown text={block.text} />
						{:else}
							<ChatChart component={block.component} config={block.config} />
						{/if}
					{/each}
					{#if item.status}
						<p class="tool-status">{item.status}</p>
					{/if}
				</div>
			{:else if sending && index === items.length - 1}
				<div class="message message-assistant typing" aria-label="Kairos schreibt">…</div>
			{/if}
		{:else if item.kind === 'memory'}
			<div class="memory-chip">
				<span>
					📝 Gemerkt: {item.content}{item.expiresAt ? ` (bis ${formatDate(item.expiresAt)})` : ''}
				</span>
				{#if item.undone}
					<span>Rückgängig gemacht</span>
				{:else}
					<form
						method="POST"
						action="?/forgetRemembered"
						use:enhance={() => {
							return async ({ result }) => {
								if (result.type === 'success') item.undone = true;
								else pushError('Eintrag konnte nicht rückgängig gemacht werden.');
							};
						}}
					>
						<input type="hidden" name="memory_id" value={item.id} />
						<button type="submit" class="chip-undo">Rückgängig</button>
					</form>
				{/if}
			</div>
		{:else if item.kind === 'proposal'}
			<div class="proposal-card">
				<p>{item.summary}</p>
				{#if item.state === 'resolved'}
					{#if item.outcome}<p class="tool-status">{item.outcome}</p>{/if}
				{:else}
					<div class="proposal-actions">
						<button
							type="button"
							class="btn btn-primary"
							disabled={sending || item.state === 'busy'}
							onclick={() => resolveProposal(item, 'confirm')}
						>
							Bestätigen
						</button>
						<button
							type="button"
							class="btn btn-ghost"
							disabled={sending || item.state === 'busy'}
							onclick={() => resolveProposal(item, 'reject')}
						>
							Ablehnen
						</button>
					</div>
				{/if}
			</div>
		{:else if item.kind === 'error'}
			<p class="status-error">{item.text}</p>
		{/if}
	{/each}
</div>

<form class="chat-input-form" onsubmit={send}>
	<input
		type="text"
		name="content"
		placeholder="Frag Kairos..."
		required
		bind:value={draft}
		disabled={sending}
	/>
	<button type="submit" class="btn btn-primary" disabled={sending}>
		{sending ? 'Sendet …' : 'Senden'}
	</button>
</form>

<style>
	.message-list {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		flex: 1;
	}
	.message {
		padding: var(--space-3);
		border-radius: var(--radius-md, 8px);
		max-width: 80%;
		overflow-wrap: anywhere;
	}
	.message-user {
		align-self: flex-end;
		background: color-mix(in srgb, var(--color-accent) 20%, transparent);
		white-space: pre-wrap;
	}
	.message-assistant {
		align-self: flex-start;
		background: var(--color-surface-raised);
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.typing {
		color: var(--color-text-muted);
	}
	.tool-status {
		margin: 0;
		font-size: var(--text-sm);
		color: var(--color-text-muted);
		font-style: italic;
	}
	.memory-chip {
		align-self: flex-start;
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-2) var(--space-3);
		border-radius: 999px;
		background: var(--color-border);
		font-size: var(--text-xs);
		color: var(--color-text-muted);
	}
	.chip-undo {
		background: none;
		border: none;
		color: var(--color-accent);
		cursor: pointer;
		font-size: var(--text-xs);
		text-decoration: underline;
		padding: 0;
	}
	.proposal-card {
		align-self: flex-start;
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		padding: var(--space-3);
		border: 1px solid var(--color-accent);
		border-radius: var(--radius-md, 8px);
		max-width: 80%;
	}
	.proposal-card p {
		margin: 0;
	}
	.proposal-actions {
		display: flex;
		gap: var(--space-2);
	}
	.chat-input-form {
		display: flex;
		gap: var(--space-2);
	}
	.chat-input-form input[type='text'] {
		flex: 1;
		font: inherit;
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		padding: var(--space-2);
		color: var(--color-text);
	}
	@media (max-width: 768px) {
		.message,
		.proposal-card {
			max-width: 100%;
		}
	}
</style>
