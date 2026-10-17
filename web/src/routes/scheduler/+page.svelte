<script lang="ts">
	import { enhance } from '$app/forms';
	import { invalidate } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { onDestroy } from 'svelte';
	import StatusPill from '$lib/components/StatusPill.svelte';
	import {
		formatLocal,
		relativeTime,
		statusTone,
		STATUS_LABELS,
		TEMPLATES,
		TRIGGER_LABELS,
		type JobRun,
		type SchedulerJob
	} from '$lib/scheduler';
	import type { ActionData, PageData } from './$types';

	let { data, form }: { data: PageData; form: ActionData } = $props();

	const STEP_LABELS: Record<string, string> = {
		'garmin.sync': 'Garmin',
		'calendar.sync': 'Kalender',
		'metrics.recompute': 'Kennzahlen',
		'agent.prompt': 'Agent'
	};

	let pending = $state<Record<string, boolean>>({});
	let confirmDelete = $state<string | null>(null);
	let history = $state<Record<string, JobRun[] | 'loading' | 'error'>>({});
	let open = $state<Record<string, boolean>>({});
	let timer: ReturnType<typeof setInterval> | undefined;

	function stepNames(job: SchedulerJob): string {
		return job.steps
			.map((s) => (typeof s === 'string' ? s : s.action))
			.map((a) => STEP_LABELS[a] ?? a)
			.join(' → ');
	}

	async function loadRuns(jobId: string) {
		if (history[jobId] === undefined) history[jobId] = 'loading';
		try {
			const resp = await fetch(`/api/scheduler/jobs/${jobId}/runs?limit=20`, {
				credentials: 'include'
			});
			if (!resp.ok) throw new Error(String(resp.status));
			history[jobId] = ((await resp.json()) as { runs: JobRun[] }).runs;
		} catch {
			history[jobId] = 'error';
		}
	}

	function anyRunning(): boolean {
		return (
			data.jobs.some((j) => j.running) ||
			Object.values(history).some((h) => Array.isArray(h) && h.some((r) => r.status === 'running'))
		);
	}

	// refresh every 5 s while a run is in progress, stop when everything is idle
	function poll() {
		if (timer || !anyRunning()) return;
		timer = setInterval(async () => {
			await invalidate('scheduler:jobs');
			await Promise.all(
				Object.keys(open)
					.filter((id) => open[id])
					.map(loadRuns)
			);
			if (!anyRunning()) {
				clearInterval(timer);
				timer = undefined;
			}
		}, 5000);
	}

	$effect(() => {
		if (data.jobs.some((j) => j.running)) poll();
	});

	onDestroy(() => clearInterval(timer));

	function toggleHistory(jobId: string, isOpen: boolean) {
		open[jobId] = isOpen;
		if (isOpen) loadRuns(jobId).then(poll);
	}

	function duration(run: JobRun): string {
		if (!run.finished_at) return '…';
		const s = Math.round((Date.parse(run.finished_at) - Date.parse(run.started_at)) / 1000);
		return s < 60 ? `${s} s` : `${Math.round(s / 60)} min`;
	}
</script>

<div class="page-head">
	<div>
		<h1>Scheduler</h1>
		<p class="lede">
			Wiederkehrende Abläufe: Daten abgleichen und den Agenten zu festen Zeiten fragen.
		</p>
	</div>
	{#if data.jobs.length > 0}
		<a class="btn btn-primary" href={resolve('/scheduler/new')}>+ Neuer Job</a>
	{/if}
</div>

{#if data.jobs.length === 0}
	<div class="templates">
		{#each TEMPLATES as template, index (template.name)}
			<div class="tile template">
				<h2 class="t-subtitle">{template.name}</h2>
				<p class="t-caption">
					{template.label} ·
					{template.steps.map((s) => STEP_LABELS[s.action]).join(' → ')}
				</p>
				<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- query string on a resolved path -->
				<a class="btn btn-secondary" href={`${resolve('/scheduler/new')}?template=${index}`}
					>Als Vorlage nutzen</a
				>
			</div>
		{/each}
		<div class="tile template">
			<h2 class="t-subtitle">Eigener Job</h2>
			<p class="t-caption">Zeitplan und Schritte selbst zusammenstellen.</p>
			<a class="btn btn-secondary" href={resolve('/scheduler/new')}>Leeren Job anlegen</a>
		</div>
	</div>
{:else}
	<ul class="jobs">
		{#each data.jobs as job (job.id)}
			<li class="tile job" class:disabled={!job.enabled}>
				<div class="job-head">
					<div class="job-title">
						<h2 class="t-subtitle">{job.name}</h2>
						<p class="t-caption">{job.label} · {stepNames(job)}</p>
					</div>
					<form method="POST" action="?/toggle" use:enhance class="toggle">
						<input type="hidden" name="job_id" value={job.id} />
						<input type="hidden" name="enabled" value={String(!job.enabled)} />
						<button
							type="submit"
							class="switch"
							role="switch"
							aria-checked={job.enabled}
							aria-label="{job.name} {job.enabled ? 'ausschalten' : 'einschalten'}"
						>
							<span class="knob"></span>
						</button>
					</form>
				</div>

				<div class="job-meta">
					<span class="t-caption">
						Nächster Lauf:
						{#if job.next_run_at}
							<strong>{relativeTime(job.next_run_at)}</strong>
							({formatLocal(job.next_run_at, job.timezone)})
						{:else}
							–
						{/if}
					</span>
					{#if job.running}
						<StatusPill tone="neutral">läuft</StatusPill>
					{:else if job.last_status}
						<StatusPill tone={statusTone(job.last_status)}>
							{STATUS_LABELS[job.last_status]}{job.consecutive_failures > 1
								? ` (${job.consecutive_failures}×)`
								: ''}
						</StatusPill>
					{/if}
					{#if job.proposal_open}
						<StatusPill tone="attention">Vorschlag wartet</StatusPill>
					{/if}
				</div>

				<div class="job-actions">
					<form
						method="POST"
						action="?/run"
						use:enhance={() => {
							pending[job.id] = true;
							return async ({ update }) => {
								await update();
								pending[job.id] = false;
								poll();
							};
						}}
					>
						<input type="hidden" name="job_id" value={job.id} />
						<button
							type="submit"
							class="btn btn-secondary btn-small"
							disabled={pending[job.id] || job.running}
						>
							{pending[job.id] ? 'Startet …' : 'Jetzt ausführen'}
						</button>
					</form>
					{#if job.conversation_id}
						<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- query string on a resolved path -->
						<a class="btn btn-ghost btn-small" href={`${resolve('/chat')}?c=${job.conversation_id}`}
							>Konversation öffnen</a
						>
					{/if}
					<a class="btn btn-ghost btn-small" href={resolve('/scheduler/[id]', { id: job.id })}
						>Bearbeiten</a
					>
					{#if confirmDelete === job.id}
						<form method="POST" action="?/remove" use:enhance class="confirm">
							<input type="hidden" name="job_id" value={job.id} />
							<button type="submit" class="btn btn-ghost btn-small danger">Wirklich löschen</button>
							<button
								type="button"
								class="btn btn-ghost btn-small"
								onclick={() => (confirmDelete = null)}>Abbrechen</button
							>
						</form>
					{:else}
						<button
							type="button"
							class="btn btn-ghost btn-small"
							onclick={() => (confirmDelete = job.id)}>Löschen</button
						>
					{/if}
				</div>
				{#if form?.jobId === job.id && form?.error}
					<p class="status-error">{form.error}</p>
				{/if}

				<details ontoggle={(e) => toggleHistory(job.id, e.currentTarget.open)}>
					<summary class="t-caption">Lauf-Historie</summary>
					{#if history[job.id] === 'loading'}
						<p class="t-caption">Lädt …</p>
					{:else if history[job.id] === 'error'}
						<p class="status-error">Historie konnte nicht geladen werden.</p>
					{:else if Array.isArray(history[job.id])}
						{@const runs = history[job.id] as JobRun[]}
						{#if runs.length === 0}
							<p class="t-caption">Noch kein Lauf.</p>
						{:else}
							<ol class="runs">
								{#each runs as run (run.id)}
									<li>
										<div class="run-head">
											<span>{formatLocal(run.started_at, job.timezone)}</span>
											<span class="t-caption">{TRIGGER_LABELS[run.trigger]} · {duration(run)}</span>
											<StatusPill tone={statusTone(run.status)}
												>{STATUS_LABELS[run.status]}</StatusPill
											>
										</div>
										<ul class="run-steps">
											{#each run.steps as step, i (i)}
												<li class="t-caption" data-status={step.status}>
													<span class="step-name">{STEP_LABELS[step.action] ?? step.action}</span>
													<span
														>{step.status === 'not_run'
															? 'nicht ausgeführt'
															: (step.summary ?? step.status)}</span
													>
												</li>
											{/each}
										</ul>
									</li>
								{/each}
							</ol>
						{/if}
					{/if}
				</details>
			</li>
		{/each}
	</ul>
{/if}

<style>
	.page-head {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: var(--space-4);
		flex-wrap: wrap;
	}
	.lede {
		color: var(--text-muted);
		max-width: 36rem;
	}
	.templates {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(16rem, 1fr));
		gap: var(--space-4);
	}
	.template {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		align-items: flex-start;
	}
	.template h2,
	.job-title h2 {
		margin: 0;
	}
	.jobs {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
	}
	.job,
	.template {
		min-height: 0;
	}
	.job {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.job.disabled .job-title,
	.job.disabled .job-meta {
		opacity: 0.6;
	}
	.job-head {
		display: flex;
		justify-content: space-between;
		gap: var(--space-3);
	}
	.job-title p {
		color: var(--text-muted);
		margin: var(--space-1) 0 0;
	}
	.job-meta,
	.job-actions,
	.confirm {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2);
	}
	.job-meta strong {
		color: var(--text);
		font-weight: 500;
	}
	.danger {
		color: var(--status-deviation-text);
	}
	.switch {
		position: relative;
		width: 48px;
		min-width: 48px;
		height: 28px;
		border-radius: var(--radius-pill);
		border: none;
		background: var(--line-subtle);
		cursor: pointer;
		/* keep the tap target at the minimum size on the phone */
		margin: 8px 0;
		transition: background var(--motion-fast) var(--motion-easing);
	}
	.switch[aria-checked='true'] {
		background: var(--accent);
	}
	.knob {
		position: absolute;
		top: 4px;
		left: 4px;
		width: 20px;
		height: 20px;
		border-radius: 50%;
		background: var(--text);
		transition: transform var(--motion-fast) var(--motion-easing);
	}
	.switch[aria-checked='true'] .knob {
		transform: translateX(20px);
		background: var(--accent-ink);
	}
	details summary {
		cursor: pointer;
		color: var(--text-muted);
		min-height: var(--size-tap-min);
		display: flex;
		align-items: center;
	}
	.runs {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.run-head {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2);
	}
	.run-steps {
		list-style: none;
		padding: 0 0 0 var(--space-3);
		margin: var(--space-1) 0 0;
		border-left: 1px solid var(--line-subtle);
	}
	.run-steps li {
		display: flex;
		gap: var(--space-2);
		color: var(--text-secondary);
	}
	.run-steps li[data-status='failed'] {
		color: var(--status-deviation-text);
	}
	.run-steps li[data-status='not_run'] {
		color: var(--text-faint);
	}
	.step-name {
		min-width: 6rem;
		color: var(--text-muted);
	}
</style>
