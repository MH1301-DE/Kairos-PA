import { describe, it, expect } from 'vitest';
import { apiGet } from '../../src/lib/api';
import type { CalendarEvent, FreeSlot } from '../../src/lib/types';

describe('calendar API types', () => {
	it('apiGet resolves a typed events response', async () => {
		const fetchFn = (async () =>
			new Response(
				JSON.stringify({
					events: [
						{
							id: 'evt-1',
							summary: 'Long Run',
							description: null,
							location: null,
							start_at: '2026-03-01T07:00:00+00:00',
							end_at: '2026-03-01T08:30:00+00:00',
							all_day: false,
							status: 'confirmed',
							source: 'external'
						}
					]
				}),
				{ status: 200 }
			)) as typeof fetch;

		const result = await apiGet<{ events: CalendarEvent[] }>(fetchFn, '/api/calendar/events');
		expect(result.events[0].summary).toBe('Long Run');
	});

	it('apiGet resolves a typed free-slots response', async () => {
		const fetchFn = (async () =>
			new Response(
				JSON.stringify({
					slots: [{ start: '2026-03-01T09:00:00+00:00', end: '2026-03-01T10:00:00+00:00' }]
				}),
				{ status: 200 }
			)) as typeof fetch;

		const result = await apiGet<{ slots: FreeSlot[] }>(fetchFn, '/api/calendar/free-slots');
		expect(result.slots).toHaveLength(1);
	});
});
