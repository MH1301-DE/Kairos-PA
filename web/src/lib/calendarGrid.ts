// Pure date-grid math for the month calendar widget -- kept free of Svelte/DOM
// so the grid layout and event-bucketing logic are unit-testable without
// rendering anything.

export interface CalendarDay {
	date: string; // YYYY-MM-DD
	inCurrentMonth: boolean;
}

const WEEKDAY_LABELS = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'] as const;
const MONTH_LABELS = [
	'Januar',
	'Februar',
	'März',
	'April',
	'Mai',
	'Juni',
	'Juli',
	'August',
	'September',
	'Oktober',
	'November',
	'Dezember'
] as const;

export { WEEKDAY_LABELS };

function pad2(n: number): string {
	return String(n).padStart(2, '0');
}

function toDateKey(d: Date): string {
	return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

/**
 * Always 42 days (6 full Monday-start weeks) covering `month` (1-12) of
 * `year`, padded with the trailing days of the previous/next month so the
 * grid never reflows between 4/5/6-week months.
 */
export function monthGridDays(year: number, month: number): CalendarDay[] {
	const firstOfMonth = new Date(year, month - 1, 1);
	const firstWeekday = (firstOfMonth.getDay() + 6) % 7; // 0=Mon .. 6=Sun
	const gridStart = new Date(year, month - 1, 1 - firstWeekday);

	const days: CalendarDay[] = [];
	const cursor = new Date(gridStart);
	for (let i = 0; i < 42; i++) {
		days.push({ date: toDateKey(cursor), inCurrentMonth: cursor.getMonth() === month - 1 });
		cursor.setDate(cursor.getDate() + 1);
	}
	return days;
}

/** YYYY-MM-DD of the day after `dateKey` -- for building an exclusive API range end. */
export function nextDateKey(dateKey: string): string {
	const [y, m, d] = dateKey.split('-').map(Number);
	const next = new Date(y, m - 1, d + 1);
	return toDateKey(next);
}

/** The local calendar date (YYYY-MM-DD) an ISO timestamp falls on, in the browser/server's own timezone. */
export function localDateKey(iso: string): string {
	return toDateKey(new Date(iso));
}

/**
 * Every local calendar day (YYYY-MM-DD) a calendar event touches, so a
 * multi-day event renders on each of its days instead of only its start day.
 *
 * All-day events use Google Calendar's exclusive end-date convention (a
 * 2-day event "Mon 00:00 -> Wed 00:00" covers Mon+Tue, not Wed) -- see
 * src/kairos/connectors/google_calendar/normalize.py's _parse_boundary,
 * which encodes the boundary as UTC-midnight-of-that-calendar-date and
 * carries Google's `end.date` straight through as end_at. Read with UTC
 * getters (not local, and not "subtract one millisecond then read local
 * getters" -- that shifts a day in any timezone ahead of UTC, e.g. CEST,
 * since UTC midnight isn't local midnight there) so the recovered calendar
 * date is the same regardless of the viewer's timezone. Timed events use
 * their actual local instant instead, so an event crossing local midnight
 * (e.g. 23:00 -> 01:00) still shows on both days.
 */
export function eventDayKeys(startAt: string, endAt: string, allDay: boolean): string[] {
	const start = new Date(startAt);
	const end = new Date(endAt);

	let cursor: Date;
	let lastDay: Date;
	if (allDay) {
		cursor = new Date(start.getUTCFullYear(), start.getUTCMonth(), start.getUTCDate());
		lastDay = new Date(end.getUTCFullYear(), end.getUTCMonth(), end.getUTCDate());
		lastDay.setDate(lastDay.getDate() - 1); // exclusive end -> last real day
	} else {
		cursor = new Date(start.getFullYear(), start.getMonth(), start.getDate());
		lastDay = new Date(end.getFullYear(), end.getMonth(), end.getDate());
	}

	const keys: string[] = [];
	while (cursor <= lastDay) {
		keys.push(toDateKey(cursor));
		cursor.setDate(cursor.getDate() + 1);
	}
	return keys;
}

export function monthLabel(year: number, month: number): string {
	return `${MONTH_LABELS[month - 1]} ${year}`;
}

export function todayKey(): string {
	return toDateKey(new Date());
}

/** Clamps month to 1-12, rolling the year over -- used by prev/next navigation. */
export function shiftMonth(year: number, month: number, delta: number): { year: number; month: number } {
	const total = year * 12 + (month - 1) + delta;
	return { year: Math.floor(total / 12), month: (((total % 12) + 12) % 12) + 1 };
}
