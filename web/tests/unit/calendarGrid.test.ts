import { describe, it, expect } from 'vitest';
import {
	monthGridDays,
	nextDateKey,
	localDateKey,
	monthLabel,
	shiftMonth,
	eventDayKeys
} from '../../src/lib/calendarGrid';

describe('monthGridDays', () => {
	it('always returns exactly 42 days (6 Monday-start weeks)', () => {
		// September 2026 starts on a Tuesday and has 30 days -- a real case
		// that needs both leading (Mon 31 Aug) and trailing padding days
		expect(monthGridDays(2026, 9)).toHaveLength(42);
		// February 2027 (not a leap year, 28 days, starts on a Monday) --
		// the shortest possible month, still needs trailing padding to 42
		expect(monthGridDays(2027, 2)).toHaveLength(42);
	});

	it('starts on a Monday and pads the previous month for a month starting mid-week', () => {
		const days = monthGridDays(2026, 9); // Sept 1 2026 is a Tuesday
		expect(days[0].date).toBe('2026-08-31');
		expect(days[0].inCurrentMonth).toBe(false);
		expect(days[1].date).toBe('2026-09-01');
		expect(days[1].inCurrentMonth).toBe(true);
	});

	it('marks every day of the target month as inCurrentMonth and no others in a short window around it', () => {
		const days = monthGridDays(2026, 9);
		const septDays = days.filter((d) => d.inCurrentMonth);
		expect(septDays).toHaveLength(30);
		expect(septDays[0].date).toBe('2026-09-01');
		expect(septDays[29].date).toBe('2026-09-30');
	});

	it('pads trailing days into the next month to complete the last week', () => {
		const days = monthGridDays(2026, 9);
		const last = days[days.length - 1];
		expect(last.inCurrentMonth).toBe(false);
		expect(last.date > '2026-09-30').toBe(true);
	});
});

describe('nextDateKey', () => {
	it('rolls over month and year boundaries correctly', () => {
		expect(nextDateKey('2026-09-30')).toBe('2026-10-01');
		expect(nextDateKey('2026-12-31')).toBe('2027-01-01');
	});
});

describe('localDateKey', () => {
	it('extracts the local calendar date from an ISO timestamp', () => {
		expect(localDateKey('2026-09-08T14:30:00')).toBe('2026-09-08');
	});
});

describe('monthLabel', () => {
	it('renders a German month name and year', () => {
		expect(monthLabel(2026, 9)).toBe('September 2026');
		expect(monthLabel(2027, 1)).toBe('Januar 2027');
	});
});

describe('eventDayKeys', () => {
	it('returns a single day for a normal timed event', () => {
		expect(eventDayKeys('2026-09-08T14:00:00', '2026-09-08T15:00:00', false)).toEqual([
			'2026-09-08'
		]);
	});

	it('spans a multi-day all-day event using Google Calendar\'s exclusive end date', () => {
		// real case reported live: a "Workshop" stored as start=2026-09-15T00:00Z,
		// end=2026-09-17T00:00Z (Google's end.date is exclusive) actually runs
		// Mon 15 -> Tue 16, not through Wed 17 -- was rendered only on the 15th
		// before this fix, which is the bug that was reported
		expect(eventDayKeys('2026-09-15T00:00:00Z', '2026-09-17T00:00:00Z', true)).toEqual([
			'2026-09-15',
			'2026-09-16'
		]);
	});

	it('returns a single day for a 1-day all-day event', () => {
		expect(eventDayKeys('2026-09-15T00:00:00Z', '2026-09-16T00:00:00Z', true)).toEqual([
			'2026-09-15'
		]);
	});

	it('spans both days for a timed event crossing midnight', () => {
		expect(eventDayKeys('2026-09-08T23:00:00', '2026-09-09T01:00:00', false)).toEqual([
			'2026-09-08',
			'2026-09-09'
		]);
	});
});

describe('shiftMonth', () => {
	it('moves forward within a year', () => {
		expect(shiftMonth(2026, 9, 1)).toEqual({ year: 2026, month: 10 });
	});

	it('rolls over to the next year', () => {
		expect(shiftMonth(2026, 12, 1)).toEqual({ year: 2027, month: 1 });
	});

	it('rolls back over the previous year', () => {
		expect(shiftMonth(2026, 1, -1)).toEqual({ year: 2025, month: 12 });
	});

	it('handles multi-month jumps in both directions', () => {
		expect(shiftMonth(2026, 9, 6)).toEqual({ year: 2027, month: 3 });
		expect(shiftMonth(2026, 9, -12)).toEqual({ year: 2025, month: 9 });
	});
});
