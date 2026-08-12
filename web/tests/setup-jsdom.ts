// jsdom implements no ResizeObserver (jsdom#4951). EChartsBase installs one to
// keep charts sized with the reflowing dashboard grid, so the component tests
// need a stub — same class of environment gap as the svg-renderer workaround.
class ResizeObserverStub implements ResizeObserver {
	observe(): void {}
	unobserve(): void {}
	disconnect(): void {}
}

if (typeof globalThis.ResizeObserver === 'undefined') {
	globalThis.ResizeObserver = ResizeObserverStub;
}
