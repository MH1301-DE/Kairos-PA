<!-- web/src/routes/sync/+page.svelte -->
<script lang="ts">
	import { enhance } from '$app/forms';
	import { invalidate } from '$app/navigation';
	import { onDestroy } from 'svelte';
	import { resolve } from '$app/paths';
	import type { PageData, ActionData } from './$types';

	let { data, form }: { data: PageData; form: ActionData } = $props();
	let garminConnection = $derived(data.connections.find((c) => c.connector === 'garmin'));

	// polls while any job is queued/running; stops once every job is done/failed/skipped
	const ACTIVE_STATUSES = new Set(['queued', 'running']);

	// Derived from data.jobs (server truth, refreshed by load() on every poll
	// tick AND on a plain page reload) rather than local component state --
	// that's what makes "backfill running" survive a reload instead of only
	// reflecting the few hundred ms the POST itself takes.
	let hasActiveGarminJob = $derived(
		data.jobs.some((j) => j.connector === 'garmin' && ACTIVE_STATUSES.has(j.status))
	);
	let hasActiveCalendarJob = $derived(
		data.jobs.some((j) => j.connector === 'google_calendar' && ACTIVE_STATUSES.has(j.status))
	);

	// single "Sync starten" dropdown for all connector triggers -- add a new
	// form + button here (and a matching action in +page.server.ts) when a
	// future service needs its own trigger, instead of one button per service
	let syncMenuOpen = $state(false);
	let syncMenuRoot: HTMLDivElement | undefined = $state();
	let triggeringGarmin = $state(false);
	let triggeringCalendar = $state(false);

	function handleWindowClick(event: MouseEvent) {
		if (syncMenuOpen && syncMenuRoot && !syncMenuRoot.contains(event.target as Node)) {
			syncMenuOpen = false;
		}
	}

	let pollHandle: ReturnType<typeof setInterval> | undefined;

	$effect(() => {
		const hasActiveJob = data.jobs.some((j) => ACTIVE_STATUSES.has(j.status));
		if (hasActiveJob && !pollHandle) {
			pollHandle = setInterval(() => invalidate('sync:status'), 2000);
		} else if (!hasActiveJob && pollHandle) {
			clearInterval(pollHandle);
			pollHandle = undefined;
		}
	});

	function progressLabel(job: PageData['jobs'][number]): string {
		if (job.windows_total === null || job.windows_total === 0) {
			return String(job.windows_processed);
		}
		const pct = Math.round((job.windows_processed / job.windows_total) * 100);
		return `${job.windows_processed} / ${job.windows_total} (${pct}%)`;
	}

	onDestroy(() => {
		if (pollHandle) clearInterval(pollHandle);
	});
</script>

<svelte:window onclick={handleWindowClick} />

<div class="sync-header">
	<h1>Sync-Status</h1>
	{#if garminConnection}
		<div class="menu-root" bind:this={syncMenuRoot}>
			<button
				type="button"
				class="btn btn-primary menu-trigger"
				aria-expanded={syncMenuOpen}
				onclick={() => (syncMenuOpen = !syncMenuOpen)}
			>
				Sync starten ▾
			</button>
			{#if syncMenuOpen}
				<div class="menu-panel" role="menu">
					<form
						method="POST"
						action="?/triggerBackfill"
						use:enhance={() => {
							triggeringGarmin = true;
							return async ({ update }) => {
								await update();
								triggeringGarmin = false;
							};
						}}
					>
						<button
							type="submit"
							class="btn btn-secondary menu-action"
							disabled={triggeringGarmin || hasActiveGarminJob}
						>
							{#if hasActiveGarminJob}
								Garmin-Backfill läuft …
							{:else if triggeringGarmin}
								Startet …
							{:else}
								Garmin-Backfill starten
							{/if}
						</button>
					</form>
					<form
						method="POST"
						action="?/triggerCalendarSync"
						use:enhance={() => {
							triggeringCalendar = true;
							return async ({ update }) => {
								await update();
								triggeringCalendar = false;
							};
						}}
					>
						<button
							type="submit"
							class="btn btn-secondary menu-action"
							disabled={triggeringCalendar || hasActiveCalendarJob}
						>
							{#if hasActiveCalendarJob}
								Kalender-Sync läuft …
							{:else if triggeringCalendar}
								Startet …
							{:else}
								Kalender synchronisieren
							{/if}
						</button>
					</form>
				</div>
			{/if}
		</div>
	{/if}
</div>

{#if !garminConnection}
	<div class="tile">
		<p>Keine Garmin-Verbindung.</p>
		<a href={resolve('/onboarding')} class="btn btn-primary">Jetzt einrichten</a>
	</div>
{:else}
	{#if form?.triggerError}
		<p class="status-error">{form.triggerError}</p>
	{/if}

	<div class="tile">
		<table>
			<thead>
				<tr>
					<th>Kind</th>
					<th>Status</th>
					<th>Fortschritt</th>
					<th>Fehler</th>
				</tr>
			</thead>
			<tbody>
				{#each data.jobs as job (job.job_id)}
					<tr>
						<td>{job.kind}</td>
						<td>{job.status}</td>
						<td>
							{#if job.windows_total}
								<progress value={job.windows_processed} max={job.windows_total}
								></progress>
							{/if}
							<span class="progress-label">{progressLabel(job)}</span>
						</td>
						<td>{job.error ?? '–'}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{/if}

<style>
	.sync-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-4);
		margin-bottom: var(--space-4);
	}
	.menu-root {
		position: relative;
	}
	.menu-trigger {
		font-size: var(--text-sm);
	}
	.menu-panel {
		position: absolute;
		right: 0;
		top: calc(100% + var(--space-2));
		width: 16rem;
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md, 8px);
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15);
		padding: var(--space-3);
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		z-index: 50;
	}
	.menu-action {
		width: 100%;
		text-align: left;
	}
	form:has(.menu-action) {
		display: contents;
	}
	progress {
		vertical-align: middle;
		margin-right: var(--space-2, 0.5rem);
		width: 8rem;
	}
	.progress-label {
		color: var(--color-text-muted);
		font-variant-numeric: tabular-nums;
	}
</style>
