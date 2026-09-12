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

async function apiRequest<T>(
	method: 'POST' | 'PUT' | 'PATCH' | 'DELETE',
	fetchFn: typeof fetch,
	path: string,
	body?: unknown
): Promise<{ status: number; data: T }> {
	const resp = await fetchFn(path, {
		method,
		credentials: 'include',
		headers: { 'Content-Type': 'application/json' },
		body: body === undefined ? undefined : JSON.stringify(body)
	});
	// a proxy/gateway error yields HTML or an empty body — degrade so callers
	// can still branch on the status code instead of crashing on a SyntaxError
	let data: T;
	try {
		data = (await resp.json()) as T;
	} catch {
		data = {} as T;
	}
	return { status: resp.status, data };
}

export async function apiPost<T>(
	fetchFn: typeof fetch,
	path: string,
	body: unknown
): Promise<{ status: number; data: T }> {
	return apiRequest<T>('POST', fetchFn, path, body);
}

export async function apiPut<T>(
	fetchFn: typeof fetch,
	path: string,
	body: unknown
): Promise<{ status: number; data: T }> {
	return apiRequest<T>('PUT', fetchFn, path, body);
}

export async function apiPatch<T>(
	fetchFn: typeof fetch,
	path: string,
	body: unknown
): Promise<{ status: number; data: T }> {
	return apiRequest<T>('PATCH', fetchFn, path, body);
}

export async function apiDelete<T>(fetchFn: typeof fetch, path: string): Promise<{ status: number; data: T }> {
	return apiRequest<T>('DELETE', fetchFn, path);
}
