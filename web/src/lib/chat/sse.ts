import { ApiError } from '$lib/api';

export type ChatEvent = { type: string; data: Record<string, unknown> };

function parseFrame(frame: string): ChatEvent | null {
	let type = 'message';
	const dataLines: string[] = [];
	for (const line of frame.split('\n')) {
		if (line.startsWith('event:')) type = line.slice(6).trim();
		else if (line.startsWith('data:')) dataLines.push(line.slice(5).replace(/^ /, ''));
	}
	if (dataLines.length === 0) return null;
	try {
		const data = JSON.parse(dataLines.join('\n')) as unknown;
		const obj = data && typeof data === 'object' ? (data as Record<string, unknown>) : {};
		return { type, data: obj };
	} catch {
		return null;
	}
}

export async function* readSse(body: ReadableStream<Uint8Array>): AsyncGenerator<ChatEvent> {
	const reader = body.getReader();
	const decoder = new TextDecoder();
	let buffer = '';
	try {
		while (true) {
			const { value, done } = await reader.read();
			if (done) break;
			buffer += decoder.decode(value, { stream: true });
			// normalize only complete CRLFs; a lone trailing \r may be half of a split \r\n
			buffer = buffer.replace(/\r\n/g, '\n');
			let sep: number;
			while ((sep = buffer.indexOf('\n\n')) !== -1) {
				const frame = buffer.slice(0, sep);
				buffer = buffer.slice(sep + 2);
				const ev = parseFrame(frame);
				if (ev) yield ev;
			}
		}
		buffer = (buffer + decoder.decode()).replace(/\r\n?/g, '\n');
		for (const frame of buffer.split('\n\n')) {
			const ev = parseFrame(frame);
			if (ev) yield ev;
		}
	} finally {
		reader.releaseLock();
	}
}

export async function postStream(path: string, body?: unknown): Promise<AsyncGenerator<ChatEvent>> {
	const resp = await fetch(path, {
		method: 'POST',
		credentials: 'include',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body ?? {})
	});
	if (!resp.ok || !resp.body) {
		throw new ApiError(resp.status, `POST ${path} failed with ${resp.status}`);
	}
	return readSse(resp.body);
}
