<script lang="ts">
	import { enhance } from '$app/forms';
	import { resolve } from '$app/paths';
	import { untrack } from 'svelte';
	import {
		cronToPreset,
		formatLocal,
		HOUR_STEPS,
		MAX_TIMES,
		MINUTE_STEPS,
		presetToCron,
		schemaToFields,
		WEEKDAYS,
		type JobStep,
		type Preset,
		type SchedulerAction,
		type SchedulerJob
	} from '$lib/scheduler';

	let {
		actions,
		defaultTimezone,
		job = null,
		template = null,
		errors = {}
	}: {
		actions: SchedulerAction[];
		defaultTimezone: string;
		job?: SchedulerJob | null;
		template?: { name: string; preset: Preset; steps: JobStep[] } | null;
		errors?: Record<string, string>;
	} = $props();

	const byName = $derived(Object.fromEntries(actions.map((a) => [a.name, a])));

	// the form owns its state from here on; props only seed it
	const seed = untrack(() => ({ job, template, defaultTimezone }));
	let name = $state(seed.job?.name ?? seed.template?.name ?? '');
	const initialPreset: Preset = (seed.job?.cron_exprs && cronToPreset(seed.job.cron_exprs)) ??
		seed.template?.preset ?? { kind: 'daily', time: '08:00' };
	let preset = $state<Preset>(structuredClone(initialPreset));
	let timezone = $state(seed.job?.timezone ?? seed.defaultTimezone);
	let steps = $state<JobStep[]>(
		structuredClone((seed.job?.steps as JobStep[] | undefined) ?? seed.template?.steps ?? [])
	);
	let resetEvery = $state(seed.job?.context_reset_every ?? 1);
	let addAction = $state('');
	let windowed = $state(
		(initialPreset.kind === 'minutes' || initialPreset.kind === 'hours') &&
			initialPreset.from !== null
	);

	const hasAgent = $derived(steps.some((s) => s.action === 'agent.prompt'));
	const resetMode = $derived(resetEvery === 0 ? 'never' : resetEvery === 1 ? 'every' : 'n');
	const timezones =
		typeof Intl.supportedValuesOf === 'function' ? Intl.supportedValuesOf('timeZone') : [];

	function setKind(kind: Preset['kind']) {
		if (kind === preset.kind) return;
		const time = 'time' in preset ? preset.time : '08:00';
		if (kind === 'daily') preset = { kind, time };
		else if (kind === 'weekdays') preset = { kind, time, days: [1] };
		else if (kind === 'times') preset = { kind, times: [time] };
		else if (kind === 'minutes')
			preset = { kind, every: 30, from: windowed ? 8 : null, to: windowed ? 20 : null };
		else preset = { kind, every: 2, from: windowed ? 8 : null, to: windowed ? 20 : null };
	}

	function setWindow(on: boolean) {
		windowed = on;
		if (preset.kind === 'minutes' || preset.kind === 'hours') {
			preset = { ...preset, from: on ? 8 : null, to: on ? 20 : null };
		}
	}

	function toggleDay(day: number) {
		if (preset.kind !== 'weekdays') return;
		const days = preset.days.includes(day)
			? preset.days.filter((d) => d !== day)
			: [...preset.days, day];
		preset = { ...preset, days };
	}

	function move(index: number, by: number) {
		const target = index + by;
		if (target < 0 || target >= steps.length) return;
		[steps[index], steps[target]] = [steps[target], steps[index]];
	}

	function addStep() {
		if (!addAction) return;
		steps.push({ action: addAction, params: {} });
		addAction = '';
	}

	function multiValue(step: JobStep, field: string): string[] {
		const v = step.params[field];
		return Array.isArray(v) ? (v as string[]) : [];
	}

	function toggleMulti(step: JobStep, field: string, value: string) {
		const current = multiValue(step, field);
		const next = current.includes(value) ? current.filter((v) => v !== value) : [...current, value];
		// an empty selection means "all", which the schema expresses as null
		step.params[field] = next.length ? next : null;
	}

	const cronExprs = $derived(presetToCron(preset));
	const payload = $derived(
		JSON.stringify({
			name,
			cron_exprs: cronExprs,
			timezone,
			enabled: job?.enabled ?? true,
			steps,
			context_reset_every: hasAgent ? resetEvery : 1
		})
	);

	let preview = $state<{ label: string | null; next: { utc: string }[]; errors: string[] } | null>(
		null
	);
	let previewTimer: ReturnType<typeof setTimeout> | undefined;
	$effect(() => {
		const body = JSON.stringify({ cron_exprs: cronExprs, timezone });
		clearTimeout(previewTimer);
		previewTimer = setTimeout(async () => {
			try {
				const resp = await fetch('/api/scheduler/preview', {
					method: 'POST',
					credentials: 'include',
					headers: { 'Content-Type': 'application/json' },
					body
				});
				preview = resp.ok ? await resp.json() : null;
			} catch {
				preview = null;
			}
		}, 300);
		return () => clearTimeout(previewTimer);
	});

	let saving = $state(false);
</script>

<form
	method="POST"
	action="?/save"
	class="editor"
	use:enhance={() => {
		saving = true;
		return async ({ update }) => {
			await update({ reset: false });
			saving = false;
		};
	}}
>
	<input type="hidden" name="payload" value={payload} />
	{#if errors.jobs}<p class="status-error">{errors.jobs}</p>{/if}

	<section class="tile">
		<label class="field">
			Name
			<input type="text" bind:value={name} maxlength="80" required aria-invalid={!!errors.name} />
		</label>
		{#if errors.name}<p class="field-error">{errors.name}</p>{/if}
	</section>

	<section class="tile">
		<h2 class="t-subtitle">Zeitplan</h2>
		<label class="field">
			Rhythmus
			<select
				value={preset.kind}
				onchange={(e) => setKind(e.currentTarget.value as Preset['kind'])}
			>
				<option value="daily">Täglich um …</option>
				<option value="weekdays">An bestimmten Wochentagen</option>
				<option value="times">Mehrmals täglich zu festen Uhrzeiten</option>
				<option value="minutes">Alle N Minuten</option>
				<option value="hours">Alle N Stunden</option>
			</select>
		</label>

		{#if preset.kind === 'daily' || preset.kind === 'weekdays'}
			<label class="field">
				Uhrzeit
				<input type="time" bind:value={preset.time} required />
			</label>
		{/if}
		{#if preset.kind === 'weekdays'}
			<div class="days" role="group" aria-label="Wochentage">
				{#each WEEKDAYS as day (day.value)}
					<button
						type="button"
						class="day"
						aria-pressed={preset.days.includes(day.value)}
						onclick={() => toggleDay(day.value)}>{day.label}</button
					>
				{/each}
			</div>
		{/if}
		{#if preset.kind === 'times'}
			{#each preset.times as time, i (i)}
				<div class="row">
					<input
						class="input"
						type="time"
						bind:value={preset.times[i]}
						required
						aria-label="Uhrzeit {i + 1}: {time}"
					/>
					{#if preset.times.length > 1}
						<button
							type="button"
							class="btn btn-ghost btn-small"
							onclick={() => preset.kind === 'times' && preset.times.splice(i, 1)}>Entfernen</button
						>
					{/if}
				</div>
			{/each}
			{#if preset.times.length < MAX_TIMES}
				<button
					type="button"
					class="btn btn-ghost btn-small"
					onclick={() => preset.kind === 'times' && preset.times.push('12:00')}>+ Uhrzeit</button
				>
			{/if}
		{/if}
		{#if preset.kind === 'minutes' || preset.kind === 'hours'}
			<label class="field">
				Abstand
				<select bind:value={preset.every}>
					{#each preset.kind === 'minutes' ? MINUTE_STEPS : HOUR_STEPS as n (n)}
						<option value={n}
							>{n} {preset.kind === 'minutes' ? 'Minuten' : n === 1 ? 'Stunde' : 'Stunden'}</option
						>
					{/each}
				</select>
			</label>
			<label class="check">
				<input
					type="checkbox"
					checked={windowed}
					onchange={(e) => setWindow(e.currentTarget.checked)}
				/>
				Nur zwischen bestimmten Uhrzeiten
			</label>
			{#if windowed && preset.from !== null && preset.to !== null}
				<div class="row">
					<label class="field">
						von
						<input type="number" min="0" max="23" bind:value={preset.from} />
					</label>
					<label class="field">
						bis
						<input type="number" min="0" max="23" bind:value={preset.to} />
					</label>
				</div>
			{/if}
		{/if}

		<details class="tz">
			<summary class="t-caption">Zeitzone: {timezone}</summary>
			<label class="field">
				Zeitzone
				<input
					type="text"
					list="timezones"
					bind:value={timezone}
					aria-invalid={!!errors.timezone}
				/>
				<datalist id="timezones">
					{#each timezones as tz (tz)}<option value={tz}></option>{/each}
				</datalist>
			</label>
		</details>
		{#if errors.timezone}<p class="field-error">{errors.timezone}</p>{/if}
		{#if errors.cron_exprs}<p class="field-error">{errors.cron_exprs}</p>{/if}

		<div class="preview" aria-live="polite">
			{#if preview?.errors.length}
				<p class="field-error">{preview.errors[0]}</p>
			{:else if preview?.label}
				<p class="t-caption"><strong>{preview.label}</strong> · nächste Läufe:</p>
				<ul>
					{#each preview.next as run (run.utc)}<li class="t-caption">
							{formatLocal(run.utc, timezone)}
						</li>{/each}
				</ul>
			{/if}
		</div>
	</section>

	<section class="tile">
		<h2 class="t-subtitle">Schritte</h2>
		{#if errors.steps}<p class="field-error">{errors.steps}</p>{/if}
		<ol class="steps">
			{#each steps as step, i (i)}
				{@const action = byName[step.action]}
				<li class="step">
					<div class="step-head">
						<span class="step-number">{i + 1}.</span>
						<strong>{action?.label ?? step.action}</strong>
						<div class="step-buttons">
							<button
								type="button"
								class="btn btn-ghost btn-small"
								aria-label="Nach oben"
								disabled={i === 0}
								onclick={() => move(i, -1)}>↑</button
							>
							<button
								type="button"
								class="btn btn-ghost btn-small"
								aria-label="Nach unten"
								disabled={i === steps.length - 1}
								onclick={() => move(i, 1)}>↓</button
							>
							<button
								type="button"
								class="btn btn-ghost btn-small"
								onclick={() => steps.splice(i, 1)}>Entfernen</button
							>
						</div>
					</div>
					{#if action}
						<p class="t-caption hint">{action.description}</p>
						{#each schemaToFields(action.schema) as field (field.name)}
							{@const fieldError = errors[`steps.${i}.params.${field.name}`]}
							{#if field.kind === 'select'}
								<label class="field">
									{field.label}
									<select
										value={step.params[field.name] ?? ''}
										onchange={(e) => (step.params[field.name] = e.currentTarget.value || null)}
									>
										{#each field.options as opt (opt.value)}
											<option value={opt.value ?? ''} disabled={opt.disabled}
												>{opt.label}{opt.disabled ? ' (bald)' : ''}</option
											>
										{/each}
									</select>
								</label>
							{:else if field.kind === 'multiselect'}
								<fieldset class="multi">
									<legend class="t-caption"
										>{field.label}{field.hint ? ` (${field.hint})` : ''}</legend
									>
									{#each field.options as opt (opt.value)}
										<label class="check">
											<input
												type="checkbox"
												checked={multiValue(step, field.name).includes(opt.value ?? '')}
												disabled={opt.disabled}
												onchange={() => toggleMulti(step, field.name, opt.value ?? '')}
											/>
											{opt.label}
										</label>
									{/each}
								</fieldset>
							{:else if field.kind === 'number'}
								<label class="field">
									{field.label}
									<input
										type="number"
										min={field.min}
										max={field.max}
										value={step.params[field.name] ?? field.default ?? ''}
										oninput={(e) => (step.params[field.name] = e.currentTarget.valueAsNumber)}
									/>
								</label>
							{:else if field.kind === 'textarea'}
								<label class="field">
									{field.label}
									<textarea
										rows="3"
										maxlength={field.maxLength}
										required={field.required}
										value={String(step.params[field.name] ?? '')}
										oninput={(e) => (step.params[field.name] = e.currentTarget.value)}></textarea>
								</label>
							{:else}
								<label class="field">
									{field.label}
									<input
										type="text"
										maxlength={field.maxLength}
										required={field.required}
										value={String(step.params[field.name] ?? '')}
										oninput={(e) => (step.params[field.name] = e.currentTarget.value)}
									/>
								</label>
							{/if}
							{#if fieldError}<p class="field-error">{fieldError}</p>{/if}
						{/each}
					{/if}
					{#if errors[`steps.${i}.action`]}<p class="field-error">
							{errors[`steps.${i}.action`]}
						</p>{/if}
				</li>
			{/each}
		</ol>
		<div class="row">
			<select class="input" bind:value={addAction} aria-label="Aktion wählen">
				<option value="">Aktion wählen …</option>
				{#each actions as a (a.name)}
					<option value={a.name} disabled={a.name === 'agent.prompt' && hasAgent}>{a.label}</option>
				{/each}
			</select>
			<button type="button" class="btn btn-secondary" disabled={!addAction} onclick={addStep}
				>Schritt hinzufügen</button
			>
		</div>
	</section>

	{#if hasAgent}
		<section class="tile">
			<h2 class="t-subtitle">Kontext des Agenten</h2>
			<label class="field">
				Kontext leeren
				<select
					value={resetMode}
					onchange={(e) => {
						const v = e.currentTarget.value;
						resetEvery = v === 'never' ? 0 : v === 'every' ? 1 : 7;
					}}
				>
					<option value="every">vor jedem Lauf (letzte Antwort wird zitiert)</option>
					<option value="n">alle N Läufe</option>
					<option value="never">nie</option>
				</select>
			</label>
			{#if resetMode === 'n'}
				<label class="field">
					Anzahl Läufe
					<input type="number" min="2" max="30" bind:value={resetEvery} />
				</label>
			{/if}
			{#if errors.context_reset_every}<p class="field-error">{errors.context_reset_every}</p>{/if}
		</section>
	{/if}

	<div class="row">
		<button type="submit" class="btn btn-primary" disabled={saving || steps.length === 0}>
			{saving ? 'Speichert …' : 'Speichern'}
		</button>
		<a class="btn btn-ghost" href={resolve('/scheduler')}>Abbrechen</a>
	</div>
</form>

<style>
	.editor {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		max-width: 44rem;
	}
	/* form sections size to their content, unlike dashboard tiles */
	section {
		min-height: 0;
		flex: none;
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	h2 {
		margin: 0;
	}
	.row {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-end;
		gap: var(--space-2);
	}
	.days {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}
	.day {
		min-width: var(--size-tap-min);
		min-height: var(--size-tap-min);
		border-radius: var(--radius-pill);
		border: 1px solid var(--line-subtle);
		background: transparent;
		color: var(--text-secondary);
		font: var(--type-body-sm);
		cursor: pointer;
	}
	.day[aria-pressed='true'] {
		background: var(--accent-subtle);
		border-color: var(--accent);
		color: var(--accent);
	}
	.check {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font: var(--type-body-sm);
		min-height: var(--size-tap-min);
	}
	.multi {
		border: none;
		padding: 0;
		margin: 0;
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(10rem, 1fr));
	}
	.tz summary {
		cursor: pointer;
		color: var(--text-muted);
	}
	.preview ul {
		margin: var(--space-1) 0 0;
		padding-left: var(--space-5);
	}
	.preview strong {
		color: var(--text);
		font-weight: 500;
	}
	.steps {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
	}
	.step {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		padding: var(--space-4);
		border-radius: var(--radius-md);
		background: var(--surface-raised);
	}
	.step-head {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		flex-wrap: wrap;
	}
	.step-number {
		color: var(--text-faint);
	}
	.step-buttons {
		margin-left: auto;
		display: flex;
		gap: var(--space-1);
	}
	.hint {
		color: var(--text-muted);
		margin: 0;
	}
</style>
