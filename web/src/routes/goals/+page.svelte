<!-- web/src/routes/goals/+page.svelte -->
<script lang="ts">
	import { enhance } from '$app/forms';
	import type { PageData, ActionData } from './$types';

	let { data, form }: { data: PageData; form: ActionData } = $props();

	let showForm = $state(false);

	const STATUS_LABEL: Record<string, string> = {
		active: 'aktiv',
		completed: 'erreicht',
		abandoned: 'aufgegeben'
	};

	function formatTarget(g: PageData['goals'][number]): string {
		if (g.target_value === null) return '–';
		return `${g.target_value} ${g.target_unit ?? ''}`.trim();
	}
</script>

<h1>Ziele</h1>
<p class="lede">Trage deine aktuellen Ziele ein, z.B. einen Halbmarathon mit Zielzeit.</p>

<div class="tile">
	<button type="button" class="btn btn-secondary" onclick={() => (showForm = !showForm)}>
		{showForm ? 'Abbrechen' : '+ Neues Ziel'}
	</button>

	{#if showForm}
		<form
			method="POST"
			action="?/create"
			use:enhance={() => {
				return async ({ update }) => {
					await update();
					showForm = false;
				};
			}}
			class="goal-form"
		>
			<label class="field">
				Titel
				<input type="text" name="title" placeholder="Halbmarathon Berlin" required />
			</label>
			<div class="field-row">
				<label class="field">
					Zielwert
					<input type="number" step="any" name="target_value" placeholder="90" />
				</label>
				<label class="field">
					Einheit
					<input type="text" name="target_unit" placeholder="min" />
				</label>
				<label class="field">
					Zieldatum
					<input type="date" name="target_date" />
				</label>
			</div>
			<label class="field">
				Notizen
				<textarea name="notes" rows="2" placeholder="Zielzeit 1:30h, aktueller PB 1:38h"></textarea>
			</label>
			{#if form?.createError}
				<p class="status-error">{form.createError}</p>
			{/if}
			<button type="submit" class="btn btn-primary">Ziel speichern</button>
		</form>
	{/if}
</div>

<div class="tile">
	{#if data.goals.length === 0}
		<p>Noch keine Ziele eingetragen.</p>
	{:else}
		<table>
			<thead>
				<tr>
					<th>Titel</th>
					<th>Ziel</th>
					<th>Zieldatum</th>
					<th>Status</th>
					<th>Notizen</th>
					<th></th>
				</tr>
			</thead>
			<tbody>
				{#each data.goals as goal (goal.id)}
					<tr class:goal-inactive={goal.status !== 'active'}>
						<td>{goal.title}</td>
						<td>{formatTarget(goal)}</td>
						<td>{goal.target_date ?? '–'}</td>
						<td>
							<form method="POST" action="?/updateStatus" use:enhance class="inline-form">
								<input type="hidden" name="goal_id" value={goal.id} />
								<select name="status" onchange={(e) => e.currentTarget.form?.requestSubmit()}>
									{#each Object.entries(STATUS_LABEL) as [value, label] (value)}
										<option {value} selected={goal.status === value}>{label}</option>
									{/each}
								</select>
							</form>
						</td>
						<td>{goal.notes ?? '–'}</td>
						<td>
							<form method="POST" action="?/remove" use:enhance>
								<input type="hidden" name="goal_id" value={goal.id} />
								<button type="submit" class="btn btn-ghost btn-small">Löschen</button>
							</form>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}
	{#if form?.updateError}
		<p class="status-error">{form.updateError}</p>
	{/if}
	{#if form?.deleteError}
		<p class="status-error">{form.deleteError}</p>
	{/if}
</div>

<style>
	.lede {
		color: var(--color-text-muted);
		max-width: 32rem;
	}
	.goal-form {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		margin-top: var(--space-4);
		max-width: 32rem;
	}
	.field-row {
		display: flex;
		gap: var(--space-3);
	}
	.field-row .field {
		flex: 1;
	}
	.goal-inactive {
		opacity: 0.6;
	}
	.inline-form {
		display: inline;
	}
</style>
