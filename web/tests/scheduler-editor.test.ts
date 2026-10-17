import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { tick } from 'svelte';

vi.mock('$app/forms', () => ({ enhance: () => ({ destroy() {} }) }));
vi.mock('$app/paths', () => ({ resolve: (path: string) => path }));

import JobEditor from '../src/lib/components/JobEditor.svelte';
import { TEMPLATES, type SchedulerAction } from '../src/lib/scheduler';

const ACTIONS: SchedulerAction[] = [
	{
		name: 'garmin.sync',
		label: 'Garmin synchronisieren',
		description: 'Holt neue Garmin-Daten.',
		min_interval_s: 3600,
		schema: {
			properties: {
				kinds: {
					anyOf: [
						{ type: 'array', items: { type: 'string', enum: ['sleep', 'hrv'] } },
						{ type: 'null' }
					],
					title: 'Datenarten'
				}
			}
		}
	},
	{
		name: 'calendar.sync',
		label: 'Kalender synchronisieren',
		description: 'Gleicht Termine ab.',
		min_interval_s: 900,
		schema: {
			properties: {
				calendar: {
					anyOf: [{ type: 'string', enum: ['google_calendar', 'caldav'] }, { type: 'null' }],
					title: 'Kalender'
				}
			}
		}
	},
	{
		name: 'agent.prompt',
		label: 'Agent fragen',
		description: 'Feste Frage.',
		min_interval_s: 3600,
		schema: {
			properties: { prompt: { type: 'string', maxLength: 2000, title: 'Frage an den Agenten' } },
			required: ['prompt']
		}
	}
];

function payload(container: HTMLElement): Record<string, unknown> {
	const input = container.querySelector<HTMLInputElement>('input[name="payload"]');
	return JSON.parse(input?.value ?? '{}') as Record<string, unknown>;
}

describe('JobEditor', () => {
	afterEach(() => cleanup());

	it('seeds the morning briefing template and builds the payload', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => new Response('{"label":null,"next":[],"errors":[]}'))
		);
		const { container } = render(JobEditor, {
			actions: ACTIONS,
			defaultTimezone: 'Europe/Berlin',
			template: TEMPLATES[0]
		});
		const body = payload(container);
		expect(body.name).toBe('Morgen-Briefing');
		expect(body.cron_exprs).toEqual(['0 8 * * *']);
		expect(body.timezone).toBe('Europe/Berlin');
		expect((body.steps as { action: string }[]).map((s) => s.action)).toEqual([
			'garmin.sync',
			'calendar.sync',
			'agent.prompt'
		]);
		// the agent step brings the context-reset setting, Apple calendar is not selectable yet
		expect(screen.getByText('Kontext des Agenten')).toBeTruthy();
		const apple = screen.getByRole('option', { name: /Apple Kalender/ }) as HTMLOptionElement;
		expect(apple.disabled).toBe(true);
	});

	it('moves steps with the up/down buttons and shows server errors per field', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => new Response('{"label":null,"next":[],"errors":[]}'))
		);
		const { container } = render(JobEditor, {
			actions: ACTIONS,
			defaultTimezone: 'Europe/Berlin',
			template: TEMPLATES[0],
			errors: { cron_exprs: 'Zu häufig', 'steps.2.params.prompt': 'Darf nicht leer sein' }
		});
		expect(screen.getByText('Zu häufig')).toBeTruthy();
		expect(screen.getByText('Darf nicht leer sein')).toBeTruthy();

		await fireEvent.click(screen.getAllByLabelText('Nach unten')[0]);
		await tick();
		const steps = payload(container).steps as { action: string }[];
		expect(steps.map((s) => s.action)).toEqual(['calendar.sync', 'garmin.sync', 'agent.prompt']);
	});

	it('round-trips an existing weekly job into the weekday preset', () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => new Response('{"label":null,"next":[],"errors":[]}'))
		);
		const { container } = render(JobEditor, {
			actions: ACTIONS,
			defaultTimezone: 'Europe/Berlin',
			job: {
				id: 'j1',
				name: 'Wochenanalyse',
				label: 'Sonntags 18:00',
				timezone: 'Europe/Vienna',
				enabled: true,
				next_run_at: null,
				last_status: null,
				last_run_at: null,
				last_success_at: null,
				running: false,
				conversation_id: null,
				consecutive_failures: 0,
				proposal_open: false,
				cron_exprs: ['0 18 * * 0'],
				context_reset_every: 0,
				steps: [{ action: 'garmin.sync', params: { kinds: null } }]
			}
		});
		const body = payload(container);
		expect(body.cron_exprs).toEqual(['0 18 * * 0']);
		expect(body.timezone).toBe('Europe/Vienna');
		const sunday = screen.getByRole('button', { name: 'So' });
		expect(sunday.getAttribute('aria-pressed')).toBe('true');
	});
});
