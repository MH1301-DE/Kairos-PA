<!-- web/src/lib/components/InfoTooltip.svelte -->
<script lang="ts">
	// each entry renders on its own line; a leading "Name: " prefix (up to the
	// first colon) is bolded automatically so callers just write plain text
	let { lines }: { lines: string[] } = $props();
	let open = $state(false);

	function splitLabel(line: string): { label: string | null; rest: string } {
		const idx = line.indexOf(':');
		if (idx === -1) return { label: null, rest: line };
		return { label: line.slice(0, idx), rest: line.slice(idx + 1).trim() };
	}
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
		<span class="info-bubble" role="tooltip">
			{#each lines as line (line)}
				{@const { label, rest } = splitLabel(line)}
				<span class="info-line">
					{#if label}<strong>{label}:</strong>{/if}
					{rest}
				</span>
			{/each}
		</span>
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
		width: 18rem;
		max-width: 75vw;
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
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
	.info-line {
		display: block;
	}
	.info-line strong {
		color: var(--color-text);
		font-weight: 600;
	}
</style>
