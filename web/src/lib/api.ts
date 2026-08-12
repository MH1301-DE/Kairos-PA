export class ApiError extends Error {
	status: number;
	constructor(status: number, message: string) {
		super(message);
		this.status = status;
	}
}

export async function apiGet<T>(fetchFn: typeof fetch, path: string): Promise<T> {
	const resp = await fetchFn(path, { credentials: 'include' });
	if (!resp.ok) {
		throw new ApiError(resp.status, `GET ${path} failed with ${resp.status}`);
	}
	return (await resp.json()) as T;
}

export async function apiPost<T>(
	fetchFn: typeof fetch,
	path: string,
	body: unknown
): Promise<{ status: number; data: T }> {
	const resp = await fetchFn(path, {
		method: 'POST',
		credentials: 'include',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body)
	});
	const data = (await resp.json()) as T;
	return { status: resp.status, data };
}
