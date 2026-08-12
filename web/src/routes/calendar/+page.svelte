<!-- web/src/routes/calendar/+page.svelte -->
<script lang="ts">
	import { enhance } from '$app/forms';
	import type { PageData, ActionData } from './$types';

	let { data, form }: { data: PageData; form: ActionData } = $props();
</script>

<h1>Kalender</h1>
<p class="lede">Die nächsten 14 Tage sowie freie Zeitfenster zum Vorschlagen eines Termins.</p>

<div class="tile">
	<h3>Termine</h3>
	{#if data.events.length === 0}
		<p class="empty">Keine Termine im Zeitraum.</p>
	{:else}
		<table>
			<thead>
				<tr>
					<th>Titel</th>
					<th>Start</th>
					<th>Ende</th>
					<th></th>
				</tr>
			</thead>
			<tbody>
				{#each data.events as event (event.id)}
					<tr>
						<td>{event.summary ?? '(ohne Titel)'}</td>
						<td class="figure">{new Date(event.start_at).toLocaleString('de-DE')}</td>
						<td class="figure">{new Date(event.end_at).toLocaleString('de-DE')}</td>
						<td>
							<form method="POST" action="?/delete" use:enhance>
								<input type="hidden" name="event_id" value={event.id} />
								<button type="submit" class="btn btn-ghost">Löschen</button>
							</form>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}
</div>

<div class="tile propose-tile">
	<h3>Termin vorschlagen</h3>
	<form method="POST" action="?/propose-slots" use:enhance class="propose-form">
		<label class="field">
			Dauer (Minuten)
			<input type="number" name="duration_minutes" min="15" step="15" value="60" required />
		</label>
		<button type="submit" class="btn btn-primary">Freie Slots anzeigen</button>
	</form>

	{#if form?.slots}
		<ul class="slot-list">
			{#each form.slots as slot (slot.start)}
				<li class="slot-row">
					<span class="figure">
						{new Date(slot.start).toLocaleString('de-DE')} &ndash; {new Date(
							slot.end
						).toLocaleTimeString('de-DE')}
					</span>
					<form method="POST" action="?/confirm" use:enhance>
						<input type="hidden" name="start_at" value={slot.start} />
						<input type="hidden" name="end_at" value={slot.end} />
						<input type="text" name="summary" placeholder="Titel" required />
						<button type="submit" class="btn btn-primary">Bestätigen</button>
					</form>
				</li>
			{/each}
		</ul>
	{/if}
	{#if form?.error}
		<p class="status-error">{form.error}</p>
	{/if}
	{#if form?.confirmed}
		<p class="status-success">Termin angelegt.</p>
	{/if}
</div>

<style>
	.lede {
		color: var(--color-text-muted);
		max-width: 32rem;
	}
	.propose-tile {
		margin-top: var(--space-4);
	}
	.propose-form {
		display: flex;
		align-items: flex-end;
		gap: var(--space-3);
	}
	.slot-list {
		list-style: none;
		margin: var(--space-4) 0 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.slot-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-4);
		padding: var(--space-3);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
	}
	.slot-row form {
		display: flex;
		gap: var(--space-2);
	}
	.slot-row input[type='text'] {
		font: inherit;
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		padding: var(--space-2);
		color: var(--color-text);
	}
</style>
