import { describe, it, expect } from 'vitest';
import { applyLayout, orderModules } from '../../src/lib/dashboardLayout';
import type { ModuleDef } from '../../src/lib/modules';

function fakeModule(moduleId: string): ModuleDef {
	return {
		moduleId,
		variant: 'default',
		title: moduleId,
		description: [],
		kind: 'kennzahl',
		period: 'heute',
		coverageUnit: 'Tage',
		emptyHint: '',
		askPrompt: ''
	};
}

describe('applyLayout', () => {
	const modules = [fakeModule('a'), fakeModule('b'), fakeModule('c')];

	it('sorts modules by the layout position', () => {
		const layout = [
			{ module_id: 'a', position: 2, visible: true },
			{ module_id: 'b', position: 0, visible: true },
			{ module_id: 'c', position: 1, visible: true }
		];
		expect(applyLayout(modules, layout).map((m) => m.moduleId)).toEqual(['b', 'c', 'a']);
	});

	it('filters out modules marked visible:false', () => {
		const layout = [
			{ module_id: 'a', position: 0, visible: true },
			{ module_id: 'b', position: 1, visible: false },
			{ module_id: 'c', position: 2, visible: true }
		];
		expect(applyLayout(modules, layout).map((m) => m.moduleId)).toEqual(['a', 'c']);
	});

	it('keeps a module with no matching layout entry visible, appended at the end', () => {
		const layout = [
			{ module_id: 'a', position: 0, visible: true },
			{ module_id: 'c', position: 1, visible: true }
			// 'b' has no entry -- must not silently disappear
		];
		expect(applyLayout(modules, layout).map((m) => m.moduleId)).toEqual(['a', 'c', 'b']);
	});
});

describe('orderModules', () => {
	const modules = [fakeModule('a'), fakeModule('b'), fakeModule('c')];

	it('keeps hidden modules in the result, marked visible: false', () => {
		const layout = [
			{ module_id: 'a', position: 0, visible: true },
			{ module_id: 'b', position: 1, visible: false },
			{ module_id: 'c', position: 2, visible: true }
		];
		const result = orderModules(modules, layout);
		expect(result.map((t) => t.module.moduleId)).toEqual(['a', 'b', 'c']);
		expect(result.find((t) => t.module.moduleId === 'b')?.visible).toBe(false);
	});
});
