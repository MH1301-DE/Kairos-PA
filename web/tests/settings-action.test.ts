import { describe, it, expect, vi } from 'vitest';
import { actions } from '../src/routes/settings/+page.server';

function formRequest(fields: Record<string, string>): Request {
	const body = new FormData();
	for (const [k, v] of Object.entries(fields)) body.set(k, v);
	return new Request('http://test/settings?/save', { method: 'POST', body });
}

function fakeFetch(status: number) {
	return vi.fn(async () => new Response(JSON.stringify({}), { status }));
}

async function save(fields: Record<string, string>, fetchFn: ReturnType<typeof fakeFetch>) {
	const event = { request: formRequest(fields), fetch: fetchFn } as unknown as Parameters<
		NonNullable<typeof actions.save>
	>[0];
	return actions.save!(event);
}

function sentBody(fetchFn: ReturnType<typeof fakeFetch>): unknown {
	const init = (fetchFn.mock.calls[0] as unknown[])[1] as RequestInit;
	return JSON.parse(init.body as string);
}

describe('settings save action', () => {
	it('sends empty fields as null', async () => {
		const fetchFn = fakeFetch(200);
		const result = await save(
			{ birth_date: '', hr_max_override: '214', resting_hr_override: '' },
			fetchFn
		);
		expect(result).toEqual({ saved: true });
		expect(sentBody(fetchFn)).toEqual({
			birth_date: null,
			hr_max_override: 214,
			resting_hr_override: null
		});
	});

	it('maps a backend 422 to a form failure', async () => {
		const result = await save({ hr_max_override: '250' }, fakeFetch(422));
		expect(result).toMatchObject({ status: 422, data: { saveError: expect.stringMatching(/120–230/) } });
	});

	it('rejects non-numeric input without calling the backend', async () => {
		const fetchFn = fakeFetch(200);
		const result = await save({ hr_max_override: 'abc' }, fetchFn);
		expect(result).toMatchObject({ status: 422 });
		expect(fetchFn).not.toHaveBeenCalled();
	});

	it('redirects to login on 401', async () => {
		await expect(save({ hr_max_override: '214' }, fakeFetch(401))).rejects.toMatchObject({
			status: 302,
			location: '/auth/login'
		});
	});
});
