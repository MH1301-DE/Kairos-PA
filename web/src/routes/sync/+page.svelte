<!-- web/src/routes/sync/+page.svelte -->
<script lang="ts">
	import { enhance } from '$app/forms';
	import { invalidate } from '$app/navigation';
	import { onDestroy } from 'svelte';
	import { resolve } from '$app/paths';
	import type { PageData, ActionData } from './$types';

	let { data, form }: { data: PageData; form: ActionData } = $props();
	let garminConnection = $derived(data.connections.find((c) => c.connector === 'garmin'));
	let triggering = $state(false);

	// polls while any job is queued/running; stops once every job is done/failed/skipped
	const ACTIVE_STATUSES = new Set(['queued', 'running']);

	// Derived from data.jobs (server truth, refreshed by load() on every poll
	// tick AND on a plain page reload) rather than local component state --
	// that's what makes "backfill running" survive a reload instead of only
	// reflecting the few hundred ms the POST itself takes.
	let hasActiveGarminJob = $derived(
		data.jobs.some((j) => j.connector === 'garmin' && ACTIVE_STATUSES.has(j.status))
	);

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

<h1>Sync-Status</h1>

{#if !garminConnection}
	<div class="tile">
		<p>Keine Garmin-Verbindung.</p>
		<a href={resolve('/onboarding')} class="btn btn-primary">Jetzt einrichten</a>
	</div>
{:else}
	<p class="connection-line">
		Garmin: <span class="figure">{garminConnection.status}</span>
		({garminConnection.external_account})
	</p>

	<form
		method="POST"
		action="?/triggerBackfill"
		use:enhance={() => {
			triggering = true;
			return async ({ update }) => {
				await update();
				triggering = false;
			};
		}}
		class="tile trigger-panel"
	>
		<button type="submit" class="btn btn-primary" disabled={triggering || hasActiveGarminJob}>
			{#if hasActiveGarminJob}
				Backfill läuft …
			{:else if triggering}
				Startet …
			{:else}
				Backfill starten
			{/if}
		</button>
		{#if form?.triggerError}
			<p class="status-error">{form.triggerError}</p>
		{/if}
	</form>

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
	.connection-line {
		color: var(--color-text-muted);
	}
	.trigger-panel {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		align-items: flex-start;
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
