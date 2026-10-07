<script lang="ts">
	import { onMount } from 'svelte';
	import { marked } from 'marked';
	import DOMPurify from 'dompurify';

	let { text }: { text: string } = $props();

	// DOMPurify needs a DOM; server render and hydration show escaped plain text
	let mounted = $state(false);
	onMount(() => {
		mounted = true;
	});

	const html = $derived(
		mounted ? DOMPurify.sanitize(marked.parse(text, { async: false }) as string) : ''
	);
</script>

{#if mounted}
	<!-- eslint-disable-next-line svelte/no-at-html-tags -- sanitized by DOMPurify -->
	<div class="markdown">{@html html}</div>
{:else}
	<div class="markdown plain">{text}</div>
{/if}

<style>
	.plain {
		white-space: pre-wrap;
	}
	.markdown :global(> :first-child) {
		margin-top: 0;
	}
	.markdown :global(> :last-child) {
		margin-bottom: 0;
	}
	.markdown :global(p),
	.markdown :global(ul),
	.markdown :global(ol) {
		margin: 0 0 var(--space-2);
	}
	.markdown :global(ul),
	.markdown :global(ol) {
		padding-left: 1.25rem;
	}
	.markdown :global(code) {
		font-size: 0.9em;
		background: var(--color-border);
		padding: 0 0.25em;
		border-radius: 4px;
	}
	.markdown :global(table) {
		border-collapse: collapse;
		font-size: var(--text-sm);
	}
	.markdown :global(th),
	.markdown :global(td) {
		border: 1px solid var(--color-border);
		padding: var(--space-1) var(--space-2);
	}
</style>
