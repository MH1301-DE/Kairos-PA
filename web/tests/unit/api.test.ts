import { describe, it, expect, vi } from 'vitest';
import { apiGet, apiPost, ApiError } from '../../src/lib/api';

describe('apiGet', () => {
	it('returns parsed JSON on success', async () => {
		const fetchFn = vi
			.fn()
			.mockResolvedValue(new Response(JSON.stringify({ hello: 'world' }), { status: 200 }));
		const result = await apiGet<{ hello: string }>(fetchFn, '/api/test');
		expect(result).toEqual({ hello: 'world' });
		expect(fetchFn).toHaveBeenCalledWith('/api/test', { credentials: 'include' });
	});

	it('throws ApiError on non-2xx', async () => {
		const fetchFn = vi.fn().mockResolvedValue(new Response('{}', { status: 404 }));
		await expect(apiGet(fetchFn, '/api/missing')).rejects.toThrow(ApiError);
	});
});

describe('apiPost', () => {
	it('returns status and data without throwing on non-2xx', async () => {
		const fetchFn = vi
			.fn()
			.mockResolvedValue(new Response(JSON.stringify({ detail: 'nope' }), { status: 401 }));
		const result = await apiPost(fetchFn, '/api/x', { a: 1 });
		expect(result.status).toBe(401);
		expect(result.data).toEqual({ detail: 'nope' });
		expect(fetchFn).toHaveBeenCalledWith('/api/x', {
			method: 'POST',
			credentials: 'include',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ a: 1 })
		});
	});
});
