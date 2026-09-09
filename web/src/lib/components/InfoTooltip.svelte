<!-- web/src/lib/components/InfoTooltip.svelte -->
<script lang="ts">
	let { text }: { text: string } = $props();
	let open = $state(false);
</script>

<span class="info-tooltip">
	<button
		type="button"
		class="info-trigger"
		aria-label="Erklärung zu dieser Kennzahl"
		aria-expanded={open}
		onmouseenter={() => (open = true)}
		onmouseleave={() => (open = false)}
		onfocus={() => (open = true)}
		onblur={() => (open = false)}
		onclick={() => (open = !open)}
	>
		?
	</button>
	{#if open}
		<span class="info-bubble" role="tooltip">{text}</span>
	{/if}
</span>

<style>
	.info-tooltip {
		position: relative;
		display: inline-flex;
		/* keeps the bubble from stretching the flex-column header row */
		align-self: flex-start;
	}
	.info-trigger {
		width: 1.15rem;
		height: 1.15rem;
		flex-shrink: 0;
		border-radius: 999px;
		border: 1px solid var(--color-border);
		background: transparent;
		color: var(--color-text-muted);
		font-family: var(--font-body);
		font-size: 0.7rem;
		font-weight: 600;
		line-height: 1;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		padding: 0;
		cursor: help;
		transition:
			border-color 0.15s ease,
			color 0.15s ease;
	}
	.info-trigger:hover,
	.info-trigger:focus-visible {
		border-color: var(--color-accent);
		color: var(--color-accent);
	}
	.info-bubble {
		position: absolute;
		z-index: 20;
		top: calc(100% + var(--space-2));
		left: 0;
		width: 15rem;
		max-width: 70vw;
		background: var(--color-surface-raised);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		padding: var(--space-2) var(--space-3);
		font-family: var(--font-body);
		font-size: var(--text-xs);
		font-weight: 400;
		color: var(--color-text-muted);
		line-height: 1.5;
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
		pointer-events: none;
	}
</style>
