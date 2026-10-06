<!-- web/src/routes/calendar/+page.svelte -->
<script lang="ts">
	import { enhance } from '$app/forms';
	import { untrack } from 'svelte';
	import { resolve } from '$app/paths';
	import type { PageData, ActionData } from './$types';
	import {
		monthGridDays,
		monthLabel,
		todayKey,
		shiftMonth,
		WEEKDAY_LABELS,
		eventDayKeys,
		type CalendarDay
	} from '$lib/calendarGrid';
	import type { CalendarEvent } from '$lib/types';

	let { data, form }: { data: PageData; form: ActionData } = $props();

	let days = $derived(monthGridDays(data.year, data.month));
	const today = todayKey();

	function monthHref(year: number, month: number) {
		return resolve(`/calendar?month=${year}-${String(month).padStart(2, '0')}`);
	}

	function initialSelected(gridDays: CalendarDay[]): string {
		return gridDays.some((d) => d.date === today) ? today : gridDays[0].date;
	}

	// local UI state (which day's detail panel is open) -- independent of the
	// server-loaded month. Seeded with a plain, non-reactive value (not derived
	// from props -- Svelte flags that as state_referenced_locally) and set to
	// its real initial value by the effect below, which also keeps it in sync
	// on month navigation (same pattern as the dashboard's per-tile "Stand"
	// date: a $state initializer runs once, not on every prop update).
	let selectedDate = $state(today);

	$effect(() => {
		const currentDays = days;
		// untrack() reads selectedDate without depending on it, so this effect
		// only re-runs when `days` (i.e. the viewed month) changes -- reading
		// and writing the same state in one effect otherwise risks an infinite
		// update loop (Svelte's effect_update_depth_exceeded)
		untrack(() => {
			if (!currentDays.some((d) => d.date === selectedDate)) {
				selectedDate = initialSelected(currentDays);
			}
		});
	});

	// buckets each event onto every day it spans, not just its start day --
	// a multi-day event (e.g. a 2-day workshop) needs a chip on each of its days
	let eventsByDay = $derived.by(() => {
		// rebuilt on every derivation and never mutated afterwards, so it needn't be reactive
		// eslint-disable-next-line svelte/prefer-svelte-reactivity
		const map = new Map<string, CalendarEvent[]>();
		for (const event of data.events) {
			for (const key of eventDayKeys(event.start_at, event.end_at, event.all_day)) {
				const list = map.get(key);
				if (list) list.push(event);
				else map.set(key, [event]);
			}
		}
		return map;
	});

	let selectedEvents = $derived(eventsByDay.get(selectedDate) ?? []);

	function eventTime(event: CalendarEvent): string {
		if (event.all_day) return 'ganztägig';
		return new Date(event.start_at).toLocaleTimeString('de-DE', {
			hour: '2-digit',
			minute: '2-digit'
		});
	}

	const MAX_CHIPS_PER_DAY = 3;

	// external (real Google Calendar) events need an explicit confirmation before
	// deletion -- the backend enforces this independently (?confirm=true), this
	// dialog is just the human-facing prompt. Kairos' own proposed events are
	// low-risk and delete on a single click, same as before.
	function confirmExternalDelete(event: CalendarEvent) {
		return ({ cancel }: { cancel: () => void }) => {
			if (
				event.source === 'external' &&
				!window.confirm(
					`"${event.summary ?? '(ohne Titel)'}" ist ein echter Termin aus deinem Google-Kalender. Wirklich löschen?`
				)
			) {
				cancel();
			}
		};
	}
</script>

<h1>Kalender</h1>

<div class="calendar-toolbar">
	<div class="month-nav">
		<a
			href={monthHref(
				shiftMonth(data.year, data.month, -1).year,
				shiftMonth(data.year, data.month, -1).month
			)}
			class="btn btn-ghost"
			aria-label="Vorheriger Monat">‹</a
		>
		<h2>{monthLabel(data.year, data.month)}</h2>
		<a
			href={monthHref(
				shiftMonth(data.year, data.month, 1).year,
				shiftMonth(data.year, data.month, 1).month
			)}
			class="btn btn-ghost"
			aria-label="Nächster Monat">›</a
		>
		<a
			href={monthHref(Number(today.slice(0, 4)), Number(today.slice(5, 7)))}
			class="btn btn-ghost today-link">Heute</a
		>
	</div>
	<form method="POST" action="?/sync" use:enhance>
		<button type="submit" class="btn btn-ghost">Kalender synchronisieren</button>
	</form>
</div>
{#if form?.syncStarted}
	<p class="status-success">Synchronisierung gestartet.</p>
{/if}

<div class="calendar-grid">
	{#each WEEKDAY_LABELS as label (label)}
		<div class="weekday-header">{label}</div>
	{/each}
	{#each days as day (day.date)}
		{@const dayEvents = eventsByDay.get(day.date) ?? []}
		<button
			type="button"
			class="day-cell"
			class:outside={!day.inCurrentMonth}
			class:is-today={day.date === today}
			class:selected={day.date === selectedDate}
			onclick={() => (selectedDate = day.date)}
		>
			<span class="day-number">{Number(day.date.slice(8, 10))}</span>
			<span class="day-events">
				{#each dayEvents.slice(0, MAX_CHIPS_PER_DAY) as event (event.id)}
					<span class="day-event-chip">{event.summary ?? '(ohne Titel)'}</span>
				{/each}
				{#if dayEvents.length > MAX_CHIPS_PER_DAY}
					<span class="day-event-more">+{dayEvents.length - MAX_CHIPS_PER_DAY} mehr</span>
				{/if}
			</span>
		</button>
	{/each}
</div>

<div class="tile day-detail">
	<h3>
		{new Date(`${selectedDate}T00:00:00`).toLocaleDateString('de-DE', {
			weekday: 'long',
			day: '2-digit',
			month: 'long',
			year: 'numeric'
		})}
	</h3>

	{#if selectedEvents.length === 0}
		<p class="empty">Keine Termine an diesem Tag.</p>
	{:else}
		<ul class="event-list">
			{#each selectedEvents as event (event.id)}
				<li class="event-row">
					<span class="event-time figure">{eventTime(event)}</span>
					<span class="event-summary">{event.summary ?? '(ohne Titel)'}</span>
					<form method="POST" action="?/delete" use:enhance={confirmExternalDelete(event)}>
						<input type="hidden" name="event_id" value={event.id} />
						<input type="hidden" name="confirm" value="true" />
						<button type="submit" class="btn btn-ghost">Löschen</button>
					</form>
				</li>
			{/each}
		</ul>
	{/if}

	<form method="POST" action="?/create" use:enhance class="create-form">
		<input type="hidden" name="date" value={selectedDate} />
		<label class="field">
			Titel
			<input type="text" name="summary" placeholder="Termin-Titel" required />
		</label>
		<label class="field">
			Start
			<input type="time" name="start_time" value="09:00" required />
		</label>
		<label class="field">
			Ende
			<input type="time" name="end_time" value="10:00" required />
		</label>
		<label class="field description-field">
			Notizen (optional)
			<input type="text" name="description" placeholder="Details" />
		</label>
		<button type="submit" class="btn btn-primary">Termin anlegen</button>
	</form>
	{#if form?.createError}
		<p class="status-error">{form.createError}</p>
	{/if}
	{#if form?.created}
		<p class="status-success">Termin angelegt.</p>
	{/if}
</div>

<details class="tile propose-tile">
	<summary>Termin vorschlagen (freie Zeitfenster)</summary>
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
</details>

<style>
	.calendar-toolbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-4);
		margin-bottom: var(--space-4);
	}
	.month-nav {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.month-nav h2 {
		margin: 0 var(--space-2);
		min-width: 12rem;
		text-align: center;
	}
	.today-link {
		margin-left: var(--space-2);
	}

	.calendar-grid {
		display: grid;
		grid-template-columns: repeat(7, 1fr);
		gap: 1px;
		background: var(--color-border);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md, 8px);
		overflow: hidden;
		margin-bottom: var(--space-4);
	}
	.weekday-header {
		background: var(--color-surface-raised);
		padding: var(--space-2);
		text-align: center;
		font-size: var(--text-xs);
		color: var(--color-text-muted);
	}
	.day-cell {
		background: var(--color-surface);
		min-height: 5.5rem;
		padding: var(--space-1) var(--space-2);
		display: flex;
		flex-direction: column;
		align-items: stretch;
		gap: var(--space-1);
		text-align: left;
		cursor: pointer;
		border: none;
		color: inherit;
		font: inherit;
		transition: background-color 0.1s ease;
	}
	.day-cell:hover {
		background: var(--color-surface-raised);
	}
	.day-cell.outside {
		color: var(--color-text-faint);
		opacity: 0.55;
	}
	.day-cell.selected {
		outline: 2px solid var(--color-accent);
		outline-offset: -2px;
	}
	.day-number {
		font-size: var(--text-sm);
		font-family: var(--font-mono);
	}
	.day-cell.is-today .day-number {
		color: var(--text);
		font-weight: 600;
	}
	.day-events {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.day-event-chip {
		font-size: 0.65rem;
		padding: 1px 4px;
		border-radius: 3px;
		background: var(--surface-raised);
		color: var(--text-secondary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.day-event-more {
		font-size: 0.65rem;
		color: var(--color-text-muted);
	}

	/* denser month grid on a phone -- keeps the 7-column structure (matches
	   Apple/Google Calendar's own mobile month view) rather than switching to
	   a list layout, just tightens spacing so it fits */
	@media (max-width: 640px) {
		.calendar-toolbar {
			flex-wrap: wrap;
			gap: var(--space-2);
		}
		.month-nav h2 {
			min-width: 0;
			font-size: var(--text-base);
		}
		.day-cell {
			min-height: 3.5rem;
			padding: 2px var(--space-1);
		}
		.day-number {
			font-size: var(--text-xs);
		}
		.day-event-chip,
		.day-event-more {
			font-size: 0.55rem;
			padding: 1px 2px;
		}
	}

	.day-detail {
		margin-bottom: var(--space-4);
	}
	.event-list {
		list-style: none;
		margin: 0 0 var(--space-4);
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.event-row {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-2) 0;
		border-bottom: 1px solid var(--color-border-subtle);
	}
	.event-time {
		color: var(--color-text-muted);
		min-width: 4rem;
	}
	.event-summary {
		flex: 1;
	}
	.create-form {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-end;
		gap: var(--space-3);
	}
	.field {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		font-size: var(--text-xs);
		color: var(--color-text-muted);
	}
	.field input {
		font: inherit;
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		padding: var(--space-2);
		color: var(--color-text);
	}
	.description-field {
		flex: 1;
		min-width: 10rem;
	}

	.propose-tile summary {
		cursor: pointer;
		font-family: var(--font-display);
		font-weight: 600;
		font-size: var(--text-lg);
	}
	.propose-form {
		display: flex;
		align-items: flex-end;
		gap: var(--space-3);
		margin-top: var(--space-3);
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
