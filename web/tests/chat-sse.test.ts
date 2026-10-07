import { describe, it, expect } from 'vitest';
import { readSse, type ChatEvent } from '../src/lib/chat/sse';

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
	const encoder = new TextEncoder();
	return new ReadableStream({
		start(controller) {
			for (const c of chunks) controller.enqueue(encoder.encode(c));
			controller.close();
		}
	});
}

async function collect(body: ReadableStream<Uint8Array>): Promise<ChatEvent[]> {
	const out: ChatEvent[] = [];
	for await (const ev of readSse(body)) out.push(ev);
	return out;
}

describe('readSse', () => {
	it('parses events split across chunks with CRLF line endings', async () => {
		const events = await collect(
			streamOf([
				'event: token\r\ndata: {"te',
				'xt":"Hal"}\r\n\r\nevent: tok',
				'en\r\ndata: {"text":"lo"}\r\n',
				'\r\nevent: done\r\ndata: {}\r\n\r\n'
			])
		);
		expect(events).toEqual([
			{ type: 'token', data: { text: 'Hal' } },
			{ type: 'token', data: { text: 'lo' } },
			{ type: 'done', data: {} }
		]);
	});

	it('joins multi-line data and handles a trailing event without blank line', async () => {
		const events = await collect(
			streamOf([
				'event: render\ndata: {"id":"r1",\ndata: "component":"Gauge"}\n\nevent: done\ndata: {}'
			])
		);
		expect(events).toEqual([
			{ type: 'render', data: { id: 'r1', component: 'Gauge' } },
			{ type: 'done', data: {} }
		]);
	});
});
