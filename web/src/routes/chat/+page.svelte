<!-- web/src/routes/chat/+page.svelte -->
<script lang="ts">
	import { enhance } from '$app/forms';
	import { resolve } from '$app/paths';
	import ChatThread from '$lib/chat/ChatThread.svelte';
	import type { PageData, ActionData } from './$types';

	let { data, form }: { data: PageData; form: ActionData } = $props();

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
						<!-- resolve() takes no query string; the path part below is resolved -->
						<!-- eslint-disable svelte/no-navigation-without-resolve -->
						<a
							href={`${resolve('/chat')}?c=${c.id}`}
							class:active={c.id === data.activeConversationId}
							onclick={() => (mobileListOpen = false)}
						>
							{c.title ?? 'Neue Konversation'}
						</a>
						<!-- eslint-enable svelte/no-navigation-without-resolve -->
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
			{#if form?.error}
				<p class="status-error">{form.error}</p>
			{/if}
			{#key data.activeConversationId}
				<ChatThread conversationId={data.activeConversationId} messages={data.messages} />
			{/key}
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
