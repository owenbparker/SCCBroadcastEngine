// Runs the module against a running SCC Broadcast Engine without Companion:
// '@companion-module/base' is swapped for a stand-in that records what the
// module defines. Usage: SCCBE_HOST=127.0.0.1 SCCBE_PORT=8782 node test/module.test.js
// (with no app running it only checks that the module loads and defines things).

const Module = require('module')
const assert = require('assert')
const real = require('@companion-module/base')

let Instance = null
const stub = {
	...real,
	runEntrypoint: (cls) => {
		Instance = cls
	},
	InstanceBase: class {
		constructor() {
			this.label = 'sccbe'
			this.statuses = []
			this.logs = []
			this.values = {}
		}
		updateStatus(s, msg) {
			this.statuses.push([s, msg])
		}
		log(level, msg) {
			this.logs.push([level, msg])
		}
		setActionDefinitions(d) {
			this.actionDefs = d
		}
		setFeedbackDefinitions(d) {
			this.feedbackDefs = d
		}
		setPresetDefinitions(d) {
			this.presetDefs = d
		}
		setVariableDefinitions(d) {
			this.variableDefs = d
		}
		setVariableValues(v) {
			Object.assign(this.values, v)
		}
		checkFeedbacks() {}
	},
}
const load = Module._load
Module._load = function (request, ...rest) {
	if (request === '@companion-module/base') return stub
	return load.call(this, request, ...rest)
}
require('../src/main.js')
assert(Instance, 'the module called runEntrypoint')

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const run = (inst, actionId, options) =>
	inst.actionDefs[actionId].callback({ options }, { parseVariablesInString: async (s) => s })
const fb = (inst, feedbackId, options) => inst.feedbackDefs[feedbackId].callback({ options })

async function main() {
	const inst = new Instance()
	const live = !!process.env.SCCBE_PORT
	await inst.init({ host: process.env.SCCBE_HOST || '127.0.0.1', port: process.env.SCCBE_PORT || '1', key: '', poll: 200 })
	for (const id of ['preview', 'program', 'take', 'clear', 'send', 'quick', 'team', 'control', 'ros_go', 'value', 'workspace', 'tournament'])
		assert(inst.actionDefs[id], `action ${id}`)
	for (const id of ['on_preview', 'on_program', 'engine_state', 'control_on', 'part_status', 'ros_on_air', 'disconnected'])
		assert(inst.feedbackDefs[id], `feedback ${id}`)
	if (!live) {
		await sleep(500)
		assert(fb(inst, 'disconnected', {}), 'shows not connected')
		console.log('Loads and defines everything (no app to talk to: set SCCBE_PORT to test against one)')
		await inst.destroy()
		return
	}
	await sleep(800)
	assert(inst.data && inst.data.controls, `got the app's state (${JSON.stringify(inst.logs)})`)
	assert(!fb(inst, 'disconnected', {}))
	const presets = Object.keys(inst.presetDefs)
	console.log(`${presets.length} presets, ${Object.keys(inst.data.controls).length} controls, ${inst.variableDefs.length} variables`)
	// Every preset's actions and feedbacks exist.
	for (const [id, p] of Object.entries(inst.presetDefs)) {
		for (const step of p.steps) for (const a of step.down) assert(inst.actionDefs[a.actionId], `${id}: ${a.actionId}`)
		for (const f of p.feedbacks) assert(inst.feedbackDefs[f.feedbackId], `${id}: ${f.feedbackId}`)
	}
	// GFX: a graphic on Preview, then Take, then clear.
	const g = inst.e().graphics[0]
	await run(inst, 'clear', { bus: 'both', transition: '' })
	await run(inst, 'preview', { graphic: g.id, mode: 'on' })
	assert(fb(inst, 'on_preview', { graphic: g.id }), 'graphic on Preview')
	assert(fb(inst, 'engine_state', { state: 'preview_any' }))
	await run(inst, 'program', { graphic: g.name, mode: 'on', transition: '' })
	assert(fb(inst, 'on_program', { graphic: g.id }), 'graphic on Program (by name)')
	await run(inst, 'clear', { bus: 'both', transition: '' })
	assert(!fb(inst, 'on_program', { graphic: g.id }))
	// Score, swap, best of.
	await run(inst, 'score_set', { side: 'left', value: 1 })
	assert.equal(inst.values.left_score, '1')
	const left = inst.values.left_name
	await run(inst, 'quick', { quick: 'swap_sides' })
	assert.equal(inst.values.right_name, left, 'swapped')
	await run(inst, 'quick', { quick: 'swap_sides' })
	await run(inst, 'quick', { quick: 'best_of_5' })
	assert(fb(inst, 'engine_state', { state: 'best_of_5' }))
	await run(inst, 'best_of', { value: 3 })
	await run(inst, 'score_set', { side: 'left', value: 0 })
	// A game HUD toggle, both ways, if VALORANT is running.
	if (inst.data.controls['val.tech_pause'] && inst.data.controls['val.tech_pause'].on !== null) {
		await run(inst, 'control', { id: 'val.tech_pause', mode: 'on' })
		assert(fb(inst, 'control_on', { id: 'val.tech_pause' }), 'VAL tech pause on')
		await run(inst, 'control', { id: 'val.tech_pause', mode: 'off' })
		assert(!fb(inst, 'control_on', { id: 'val.tech_pause' }), 'VAL tech pause off')
	}
	// The run of show, if it has segments.
	const segs = inst.data.ros.segments
	if (segs.length > 1) {
		await run(inst, 'ros_go', { index: 0 })
		assert(fb(inst, 'ros_on_air', { index: 0 }))
		await run(inst, 'control', { id: 'ros.next', mode: 'toggle' })
		assert(fb(inst, 'ros_on_air', { index: 1 }), 'next segment')
		assert.equal(inst.values.ros_current, segs[1].title)
		await run(inst, 'control', { id: 'ros.prev', mode: 'toggle' })
		assert(fb(inst, 'ros_on_air', { index: 0 }), 'back one')
		await run(inst, 'control', { id: 'ros.reset', mode: 'toggle' })
	}
	assert(fb(inst, 'part_status', { part: 'engine', status: 'on' }))
	const errors = inst.logs.filter(([l]) => l === 'error')
	assert.deepEqual(errors, [], 'no errors')
	console.log('All module checks passed against', inst.url())
	await inst.destroy()
}

main().catch((e) => {
	console.error(e)
	process.exit(1)
})
