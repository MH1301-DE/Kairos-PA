<!-- web/src/lib/components/ContextChip.svelte -->
<script lang="ts">
	let { label, onremove }: { label: string; onremove?: () => void } = $props();
</script>

<span class="chip-context">
	{label}
	{#if onremove}
		<button type="button" class="remove" aria-label="{label} entfernen" onclick={onremove}>×</button
		>
	{/if}
</span>

<style>
	.chip-context:has(.remove) {
		padding-right: 6px;
	}
	.remove {
		all: unset;
		width: 18px;
		height: 18px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		color: var(--text-muted);
		border-radius: 50%;
		cursor: pointer;
	}
	.remove:hover {
		color: var(--text);
	}
	.remove:focus-visible {
		box-shadow: var(--shadow-focus);
	}
</style>
