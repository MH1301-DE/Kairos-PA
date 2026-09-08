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

	<form method="POST" action="?/triggerBackfill" use:enhance class="tile trigger-panel">
		<button type="submit" class="btn btn-primary">Backfill starten</button>
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
					<th>Verarbeitete Fenster</th>
					<th>Fehler</th>
				</tr>
			</thead>
			<tbody>
				{#each data.jobs as job (job.job_id)}
					<tr>
						<td>{job.kind}</td>
						<td>{job.status}</td>
						<td>{job.windows_processed}</td>
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
</style>
