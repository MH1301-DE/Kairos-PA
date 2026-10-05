<!-- web/src/routes/chat/+page.svelte -->
<script lang="ts">
	import { enhance } from '$app/forms';
	import { resolve } from '$app/paths';
	import type { PageData, ActionData } from './$types';

	let { data, form }: { data: PageData; form: ActionData } = $props();

	function conversationHref(id: string): string {
		return `${resolve('/chat')}?c=${id}`;
	}

	let sending = $state(false);

	// below 768px the conversation list becomes a drawer instead of a fixed
	// left column -- see the max-width: 768px block in the style section below
	let mobileListOpen = $state(false);

	function handleKeydown(event: KeyboardEvent) {
		if (event.key === 'Escape') mobileListOpen = false;
	}
</script>

<svelte:window onkeydown={handleKeydown} />

<h1>Chat</h1>

<button
	type="button"
	class="btn btn-ghost mobile-list-toggle"
	onclick={() => (mobileListOpen = true)}
>
	☰ Konversationen
</button>

<div class="chat-layout">
	<aside class="conversation-list tile" class:mobile-open={mobileListOpen}>
		<div class="conversation-list-header">
			<h2 class="conversation-list-title">Konversationen</h2>
			<button
				type="button"
				class="btn btn-ghost mobile-list-close"
				aria-label="Schließen"
				onclick={() => (mobileListOpen = false)}
			>
				✕
			</button>
		</div>
		<form method="POST" action="?/newConversation" use:enhance>
			<button type="submit" class="btn btn-secondary new-conversation-btn">
				+ Neue Konversation
			</button>
		</form>
		{#if data.conversations.length === 0}
			<p class="empty">Noch keine Konversation.</p>
		{:else}
			<ul>
				{#each data.conversations as c (c.id)}
					<li>
						<a
							href={conversationHref(c.id)}
							class:active={c.id === data.activeConversationId}
							onclick={() => (mobileListOpen = false)}
						>
							{c.title ?? 'Neue Konversation'}
						</a>
					</li>
				{/each}
			</ul>
		{/if}
	</aside>
	{#if mobileListOpen}
		<button
			type="button"
			class="mobile-list-backdrop"
			aria-label="Schließen"
			onclick={() => (mobileListOpen = false)}
		></button>
	{/if}

	<div class="chat-main tile">
		{#if !data.activeConversationId}
			<p class="empty">Wähle links eine Konversation oder starte eine neue.</p>
		{:else}
			<div class="message-list">
				{#each data.messages as m (m.id)}
					{#if m.role === 'user'}
						<div class="message message-user">{m.content}</div>
					{:else if m.role === 'assistant' && m.content}
						<div class="message message-assistant">{m.content}</div>
					{/if}
				{/each}

				{#if form?.remembered}
					{#each form.remembered as entry (entry.id)}
						<div class="memory-chip">
							<span>📝 Gemerkt: {entry.content}</span>
							<form method="POST" action="?/forgetRemembered" use:enhance>
								<input type="hidden" name="memory_id" value={entry.id} />
								<button type="submit" class="chip-undo">Rückgängig</button>
							</form>
						</div>
					{/each}
				{/if}

				{#if form?.reply}
					<div class="message message-assistant">{form.reply}</div>
				{/if}

				{#if form?.proposal}
					<div class="proposal-card">
						<p>{form.proposal.summary}</p>
						<div class="proposal-actions">
							<form method="POST" action="?/confirm" use:enhance>
								<input type="hidden" name="conversation_id" value={data.activeConversationId} />
								<input type="hidden" name="tool_call_id" value={form.proposal.tool_call_id} />
								<button type="submit" class="btn btn-primary">Bestätigen</button>
							</form>
							<form method="POST" action="?/reject" use:enhance>
								<input type="hidden" name="conversation_id" value={data.activeConversationId} />
								<input type="hidden" name="tool_call_id" value={form.proposal.tool_call_id} />
								<button type="submit" class="btn btn-ghost">Ablehnen</button>
							</form>
						</div>
					</div>
				{/if}

				{#if form?.confirmResult}
					<div class="message message-assistant">{form.confirmResult.summary}</div>
				{/if}

				{#if form?.error}
					<p class="status-error">{form.error}</p>
				{/if}
			</div>

			<form
				method="POST"
				action="?/send"
				use:enhance={() => {
					sending = true;
					return async ({ update }) => {
						await update();
						sending = false;
					};
				}}
				class="chat-input-form"
			>
				<input type="hidden" name="conversation_id" value={data.activeConversationId} />
				<input
					type="text"
					name="content"
					placeholder="Frag Kairos..."
					required
					disabled={sending}
				/>
				<button type="submit" class="btn btn-primary" disabled={sending}>
					{sending ? 'Sendet …' : 'Senden'}
				</button>
			</form>
		{/if}
	</div>
</div>

<style>
	.chat-layout {
		display: grid;
		grid-template-columns: 16rem 1fr;
		gap: var(--space-4);
		align-items: start;
	}
	.conversation-list {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.new-conversation-btn {
		width: 100%;
	}
	.conversation-list ul {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}
	.conversation-list a {
		display: block;
		padding: var(--space-2);
		border-radius: var(--radius-sm);
		color: var(--color-text-muted);
		font-size: var(--text-sm);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.conversation-list a:hover,
	.conversation-list a:focus-visible {
		background: var(--color-surface-raised);
		text-decoration: none;
	}
	.conversation-list a.active {
		background: color-mix(in srgb, var(--color-accent) 15%, transparent);
		color: var(--color-accent);
	}
	.chat-main {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		min-height: 24rem;
	}
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
	}
	.message-user {
		align-self: flex-end;
		background: color-mix(in srgb, var(--color-accent) 20%, transparent);
	}
	.message-assistant {
		align-self: flex-start;
		background: var(--color-surface-raised);
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

	.mobile-list-toggle,
	.conversation-list-header,
	.mobile-list-backdrop {
		display: none;
	}

	@media (max-width: 768px) {
		.mobile-list-toggle {
			display: inline-flex;
			margin-bottom: var(--space-4);
		}
		.chat-layout {
			grid-template-columns: 1fr;
		}
		.conversation-list {
			display: none;
		}
		.conversation-list.mobile-open {
			display: flex;
			position: fixed;
			inset: 0;
			z-index: 100;
			border-radius: 0;
			padding-top: max(var(--space-4), env(safe-area-inset-top));
			padding-bottom: max(var(--space-4), env(safe-area-inset-bottom));
			overflow-y: auto;
		}
		.conversation-list-header {
			display: flex;
			align-items: center;
			justify-content: space-between;
			margin-bottom: var(--space-2);
		}
		.conversation-list-title {
			margin: 0;
		}
		.mobile-list-backdrop {
			display: block;
			position: fixed;
			inset: 0;
			z-index: 99;
			background: rgb(0 0 0 / 50%);
			border: none;
			padding: 0;
		}
	}
</style>
