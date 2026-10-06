<!-- web/src/lib/components/Kachel.svelte -->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { KachelState } from '../kachel';

	interface Action {
		label: string;
		href?: string;
		onclick?: () => void;
	}

	// one shell for every tile kind; all states keep the title row and height so nothing jumps
	let {
		title,
		period = '',
		state,
		foot = '',
		askHref = null,
		empty = null,
		error = null,
		editing = false,
		onremove,
		titleExtra,
		periodControl,
		children
	}: {
		title: string;
		period?: string;
		state: KachelState;
		foot?: string;
		askHref?: string | null;
		empty?: { title: string; body: string; action?: Action } | null;
		error?: { title: string; body: string; action?: Action } | null;
		editing?: boolean;
		onremove?: () => void;
		titleExtra?: Snippet;
		periodControl?: Snippet;
		children?: Snippet;
	} = $props();
</script>

{#snippet actionButton(action: Action, primary: boolean)}
	{#if action.href}
		<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- callers pass resolved paths -->
		<a class="btn {primary ? 'btn-primary' : 'btn-secondary'} state-action" href={action.href}
			>{action.label}</a
		>
	{:else}
		<button
			type="button"
			class="btn {primary ? 'btn-primary' : 'btn-secondary'} state-action"
			onclick={action.onclick}>{action.label}</button
		>
	{/if}
{/snippet}

<article class="kachel" data-state={state} aria-busy={state === 'laden'}>
	{#if state === 'laden'}
		<div class="sk-row">
			<span class="sk" style:width="38%"></span><span class="sk" style:width="18%"></span>
		</div>
		<span class="sk sk-metric"></span>
		<span class="sk sk-line" style:width="70%"></span>
		<span class="sk sk-body"></span>
		<span class="sk sk-foot" style:width="46%"></span>
	{:else}
		<header>
			<span class="title">
				<span class="title-text">{title}</span>
				{@render titleExtra?.()}
			</span>
			<span class="period">
				{#if periodControl}{@render periodControl()}{:else}{period}{/if}
			</span>
		</header>

		{#if state === 'ok' || state === 'teilweise'}
			<div class="body">{@render children?.()}</div>
			<footer>
				<span class="foot" class:partial={state === 'teilweise'}>{foot}</span>
				{#if askHref}
					<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- askHref is built from resolve() -->
					<a class="ask" href={askHref}>Dazu fragen →</a>
				{/if}
			</footer>
		{:else if state === 'leer' && empty}
			<div class="message">
				<p class="message-title">{empty.title}</p>
				<p class="message-body">{empty.body}</p>
				{#if empty.action}{@render actionButton(empty.action, false)}{/if}
			</div>
		{:else if state === 'fehler' && error}
			<div class="message">
				<p class="message-title">
					<span class="mark-deviation" aria-hidden="true"></span>{error.title}
				</p>
				<p class="message-body">{error.body}</p>
				{#if error.action}{@render actionButton(error.action, true)}{/if}
			</div>
		{/if}
	{/if}

	{#if editing}
		<div class="edit-layer">
			<span class="handle" aria-hidden="true"
				><span class="dots"
					><span></span><span></span><span></span><span></span><span></span><span></span></span
				>Verschieben</span
			>
			{#if onremove}
				<button type="button" class="remove" aria-label="{title} entfernen" onclick={onremove}
					>×</button
				>
			{/if}
		</div>
	{/if}
</article>

<style>
	.kachel {
		position: relative;
		height: 100%;
		min-height: 340px;
		background: var(--surface);
		border-radius: var(--radius-lg);
		padding: var(--space-6);
		display: flex;
		flex-direction: column;
		gap: 18px;
		min-width: 0;
		overflow: hidden;
	}

	header {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		gap: var(--space-3);
		font: var(--type-body);
		color: var(--text-secondary);
	}
	.title {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		min-width: 0;
	}
	.title-text {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.period {
		font: var(--type-caption);
		color: var(--text-faint);
		white-space: nowrap;
	}

	.body {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 18px;
		min-height: 0;
	}

	footer {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: var(--space-3);
		font: var(--type-caption);
		color: var(--text-faint);
	}
	.foot {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	/* "teilweise" isn't an error: the basis is just stated a step brighter */
	.foot.partial {
		color: var(--text-secondary);
	}
	.ask {
		flex: none;
		color: var(--text-muted);
		white-space: nowrap;
	}
	.ask:hover {
		color: var(--accent);
	}

	.message {
		flex: 1;
		display: flex;
		flex-direction: column;
		justify-content: center;
		gap: 10px;
		max-width: 440px;
	}
	.message p {
		margin: 0;
	}
	.message-title {
		display: flex;
		align-items: center;
		gap: 10px;
		font: var(--type-subtitle);
		color: var(--text);
	}
	.message-body {
		font: var(--type-body-sm);
		color: var(--text-secondary);
		text-wrap: pretty;
	}
	.state-action {
		align-self: flex-start;
		margin-top: 6px;
	}
	.mark-deviation {
		flex: none;
		width: 0;
		height: 0;
		border-left: 5px solid transparent;
		border-right: 5px solid transparent;
		border-bottom: 9px solid var(--status-deviation-mark);
	}

	.sk {
		display: block;
		background: var(--skeleton);
		border-radius: 7px;
		height: 14px;
		animation: skeleton-pulse 1.6s ease-in-out infinite;
	}
	.sk-row {
		display: flex;
		justify-content: space-between;
	}
	.sk-metric {
		width: 132px;
		height: 56px;
		border-radius: 10px;
	}
	.sk-line {
		height: 10px;
		border-radius: 5px;
	}
	.sk-body {
		flex: 1;
		min-height: 56px;
		border-radius: var(--radius-md);
	}
	.sk-foot {
		height: 12px;
		border-radius: 6px;
	}

	.edit-layer {
		position: absolute;
		inset: 0;
		border-radius: var(--radius-lg);
		box-shadow: inset 0 0 0 1.5px var(--data-band);
		background: color-mix(in srgb, var(--bg) 55%, transparent);
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		padding: 14px;
	}
	.handle {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 8px 12px;
		border-radius: var(--radius-pill);
		background: var(--surface-raised);
		font: var(--type-caption);
		color: var(--text-secondary);
		cursor: grab;
	}
	.dots {
		display: grid;
		grid-template-columns: repeat(2, 3px);
		gap: 3px;
	}
	.dots span {
		width: 3px;
		height: 3px;
		border-radius: 50%;
		background: var(--text-secondary);
	}
	.remove {
		all: unset;
		cursor: pointer;
		width: 32px;
		height: 32px;
		border-radius: 50%;
		background: var(--surface-raised);
		color: var(--text-secondary);
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 18px;
	}
	.remove:hover {
		color: var(--text);
	}
	.remove:focus-visible {
		box-shadow: var(--shadow-focus);
	}
</style>
