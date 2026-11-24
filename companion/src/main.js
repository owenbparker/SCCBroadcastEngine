// Bitfocus Companion module for SCC Broadcast Engine: the GFX Engine, the run
// of show, every game HUD, Multistream and the app's parts, from one connection.
//
// It polls the app's GET /api/companion a few times a second (feedbacks,
// variables, and the lists the dropdowns and presets are made from) and sends
// actions to POST /api/companion. See sccbe/companion.py in the app.
//
// From any PC it goes through the GFX Engine's port (8782): /sccbe/api/companion.
// On a HUD PC with no GFX Engine, Companion on that PC uses port 8770 (the app's
// own pages, this PC only): /api/companion.

const { InstanceBase, Regex, runEntrypoint, InstanceStatus } = require('@companion-module/base')
const { QUICK, ENGINE_STATES, PART_STATUS, choices } = require('./definitions')
const { buildPresets, COLORS } = require('./presets')

const MODES = [
	{ id: 'toggle', label: 'Toggle' },
	{ id: 'on', label: 'On' },
	{ id: 'off', label: 'Off' },
]
const SIDES = [
	{ id: 'left', label: 'Left team' },
	{ id: 'right', label: 'Right team' },
]

class BroadcastEngineInstance extends InstanceBase {
	async init(config) {
		this.config = config
		this.data = null
		this.failed = null // not known yet
		this.signature = null
		this.varSignature = null
		this.define()
		this.startPolling()
	}

	async destroy() {
		this.stopped = true
		clearTimeout(this.timer)
	}

	async configUpdated(config) {
		this.config = config
		this.failed = null
		this.startPolling()
	}

	getConfigFields() {
		return [
			{
				type: 'static-text',
				id: 'info',
				width: 12,
				label: '',
				value:
					"Enter the address of the PC SCC Broadcast Engine runs on (127.0.0.1 if it's this PC) and port 8782 (the GFX Engine's). " +
					"From another PC, the engine needs 'Let other PCs use this engine' on (Event > Outputs & Network), and its pairing code below if it asks for one. " +
					'A HUD PC without the GFX Engine: run Companion on that PC and use port 8770.',
			},
			{ type: 'textinput', id: 'host', label: 'PC address', width: 8, default: '127.0.0.1', regex: Regex.HOSTNAME },
			{ type: 'textinput', id: 'port', label: 'Port', width: 4, default: '8782', regex: Regex.PORT },
			{
				type: 'textinput',
				id: 'key',
				label: "Pairing code (only if the engine asks for one: Event > Outputs & Network on that PC)",
				width: 8,
				default: '',
			},
			{ type: 'number', id: 'poll', label: 'Check every (ms)', width: 4, default: 250, min: 100, max: 5000 },
		]
	}

	url() {
		const port = Number(this.config.port) || 8782
		const path = port === 8770 ? '/api/companion' : '/sccbe/api/companion'
		return `http://${(this.config.host || '127.0.0.1').trim()}:${port}${path}`
	}

	headers(json) {
		const h = {}
		if (json) h['Content-Type'] = 'application/json'
		if (this.config.key) h['X-SCC-Key'] = String(this.config.key).trim()
		return h
	}

	// --- talking to the app ----------------------------------------------

	startPolling() {
		clearTimeout(this.timer)
		this.updateStatus(InstanceStatus.Connecting)
		const tick = async () => {
			if (this.stopped) return
			await this.refresh()
			if (this.stopped) return
			this.timer = setTimeout(tick, Math.max(100, Number(this.config.poll) || 250))
		}
		tick()
	}

	async refresh() {
		try {
			const r = await fetch(this.url(), { headers: this.headers(false), signal: AbortSignal.timeout(3000) })
			if (r.status === 404) throw new Error('Not SCC Broadcast Engine (or an older version): update the app')
			if (r.status === 403) throw new Error("The engine doesn't allow other PCs: Event > Outputs & Network")
			if (!r.ok) throw new Error(`HTTP ${r.status}`)
			this.apply(await r.json())
			if (this.failed !== false) {
				this.updateStatus(InstanceStatus.Ok)
				this.log('info', `Connected to SCC Broadcast Engine at ${this.url()}`)
			}
			this.failed = false
		} catch (e) {
			if (this.failed !== true) {
				this.log('warn', `Can't reach SCC Broadcast Engine at ${this.url()}: ${e.message}`)
				this.updateStatus(InstanceStatus.ConnectionFailure, e.message)
			}
			this.failed = true
			this.checkFeedbacks('disconnected')
		}
	}

	apply(data) {
		this.data = data
		// New lists (graphics, transitions, controls, segments...): new dropdowns and presets.
		const e = data.engine || {}
		const signature = JSON.stringify([
			(e.graphics || []).map((g) => [g.id, g.name, g.kind]),
			(e.transitions || []).map((t) => [t.id, t.name]),
			(e.teams || []).map((t) => [t.name, t.game]),
			(e.workspaces || []).map((w) => [w.id, w.name]),
			(e.tournaments || []).map((t) => [t.id, t.name]),
			Object.entries(data.controls || {}).map(([id, c]) => [id, c.label, c.kind]),
			Object.keys(data.values || {}),
			((data.ros && data.ros.segments) || []).map((s) => s.title),
			(data.parts || []).map((p) => p.key),
		])
		if (signature !== this.signature) {
			this.signature = signature
			this.define()
		}
		const names = data.variable_names || {}
		const varSignature = JSON.stringify(Object.keys(data.variables || {}))
		if (varSignature !== this.varSignature) {
			this.varSignature = varSignature
			this.setVariableDefinitions(
				Object.keys(data.variables || {}).map((variableId) => ({ variableId, name: names[variableId] || variableId })),
			)
		}
		this.setVariableValues(data.variables || {})
		this.checkFeedbacks()
	}

	async send(body) {
		try {
			const r = await fetch(this.url(), {
				method: 'POST',
				headers: this.headers(true),
				body: JSON.stringify(body),
				signal: AbortSignal.timeout(10000),
			})
			let data = {}
			try {
				data = await r.json()
			} catch {
				// (not JSON)
			}
			if (data.code === 'key_needed') this.updateStatus(InstanceStatus.BadConfig, 'Needs the pairing code')
			if (data.controls) this.apply(data)
			if (!r.ok || data.error) throw new Error(data.error || `HTTP ${r.status}`)
		} catch (e) {
			this.log('error', `SCC Broadcast Engine: ${e.message}`)
		}
	}

	engine(body) {
		return this.send({ do: 'engine', ...body })
	}

	// --- lists from the app ------------------------------------------------

	e() {
		return (this.data && this.data.engine) || {}
	}

	graphics() {
		return this.e().graphics || []
	}

	controls(filter) {
		return Object.entries((this.data && this.data.controls) || {})
			.filter(([, c]) => !filter || filter(c))
			.map(([id, c]) => ({ id, label: `${c.group}: ${c.label}` }))
	}

	graphicOption(label = 'Graphic (or type its name)') {
		const list = this.graphics()
		return {
			type: 'dropdown',
			id: 'graphic',
			label,
			default: list.length ? list[0].id : '',
			allowCustom: true,
			choices: list.map((g) => ({ id: g.id, label: `${g.name} (${g.kind})` })),
		}
	}

	transitionOption(first) {
		const list = this.e().transitions || []
		return {
			type: 'dropdown',
			id: 'transition',
			label: 'Transition',
			default: '',
			choices: [{ id: '', label: first }, ...list.map((t) => ({ id: t.id, label: t.name }))],
		}
	}

	listOption(id, label, list, custom = true) {
		return {
			type: 'dropdown',
			id,
			label,
			default: list.length ? list[0].id : '',
			allowCustom: custom,
			choices: list,
		}
	}

	define() {
		this.setActionDefinitions(this.actions())
		this.setFeedbackDefinitions(this.feedbacks())
		this.setPresetDefinitions(buildPresets(this))
	}

	actions() {
		const teams = (this.e().teams || []).map((t) => ({
			id: t.game ? `${t.name}|${t.game}` : t.name,
			label: t.game ? `${t.name} · ${t.game}` : t.name,
		}))
		const named = (list) => (list || []).map((x) => ({ id: x.id, label: x.name }))
		const segments = ((this.data && this.data.ros && this.data.ros.segments) || []).map((s) => ({
			id: s.index,
			label: `${s.index + 1}. ${s.title}${s.block ? ` (${s.block})` : ''}`,
		}))
		const values = Object.entries((this.data && this.data.values) || {}).map(([id, v]) => ({
			id,
			label: `${v.group}: ${v.label} (${v.min} to ${v.max})`,
		}))
		return {
			// The GFX Engine.
			preview: {
				name: 'GFX: put a graphic on / off Preview',
				options: [this.graphicOption(), { type: 'dropdown', id: 'mode', label: 'Do', default: 'toggle', choices: MODES }],
				callback: (e) => this.engine({ action: 'preview', id: e.options.graphic, mode: e.options.mode }),
			},
			program: {
				name: 'GFX: take a graphic in / out of Program on its own',
				options: [
					this.graphicOption(),
					{ type: 'dropdown', id: 'mode', label: 'Do', default: 'toggle', choices: MODES },
					this.transitionOption("The graphic's own animation"),
				],
				callback: (e) =>
					this.engine({ action: 'program', id: e.options.graphic, mode: e.options.mode, transition: e.options.transition }),
			},
			take: {
				name: 'GFX: Take (Preview to Program, any transition or stinger)',
				options: [this.transitionOption('The default transition')],
				callback: (e) => this.engine({ action: 'take', transition: e.options.transition }),
			},
			clear: {
				name: 'GFX: clear Program / Preview',
				options: [
					{
						type: 'dropdown',
						id: 'bus',
						label: 'Clear',
						default: 'program',
						choices: [
							{ id: 'program', label: 'Program' },
							{ id: 'preview', label: 'Preview' },
							{ id: 'both', label: 'Both' },
						],
					},
					this.transitionOption("Each graphic's own animation"),
				],
				callback: (e) => this.engine({ action: 'clear', bus: e.options.bus, transition: e.options.transition }),
			},
			send: {
				name: 'GFX: Update Program (send the Preview values to air, no transition)',
				options: [{ ...this.graphicOption('Graphic (empty = everything on Program)'), default: '' }],
				callback: (e) => this.engine({ action: 'send', id: e.options.graphic }),
			},
			quick: {
				name: 'GFX: quick function (score, swap sides, best of, clock, timer, loops, casters)',
				options: [{ type: 'dropdown', id: 'quick', label: 'Do', default: 'score_left_up', choices: choices(QUICK) }],
				callback: (e) => this.engine({ action: 'run', id: e.options.quick }),
			},
			score_set: {
				name: 'Series: set a team’s score',
				options: [
					{ type: 'dropdown', id: 'side', label: 'Team', default: 'left', choices: SIDES },
					{ type: 'number', id: 'value', label: 'Score', default: 0, min: 0, max: 99 },
				],
				callback: (e) => this.engine({ action: 'score', side: e.options.side, value: e.options.value }),
			},
			best_of: {
				name: 'Series: best of',
				options: [{ type: 'number', id: 'value', label: 'Best of', default: 3, min: 1, max: 99 }],
				callback: (e) => this.engine({ action: 'best_of', value: e.options.value }),
			},
			team: {
				name: 'Teams: put a team from the team list on a side',
				options: [
					{ type: 'dropdown', id: 'side', label: 'Side', default: 'left', choices: SIDES },
					this.listOption('team', 'Team (or type its name)', teams),
				],
				callback: (e) => this.engine({ action: 'team', side: e.options.side, team: e.options.team }),
			},
			event_text: {
				name: 'Event: set the event or stage name',
				options: [
					{
						type: 'dropdown',
						id: 'field',
						label: 'Field',
						default: 'stage',
						choices: [
							{ id: 'event', label: 'Event' },
							{ id: 'stage', label: 'Stage' },
						],
					},
					{ type: 'textinput', id: 'value', label: 'Text', default: '', useVariables: true },
				],
				callback: async (e, context) => {
					const value = await context.parseVariablesInString(e.options.value || '')
					return this.engine({ action: 'text', field: e.options.field, value })
				},
			},
			workspace: {
				name: 'Workspace: open one',
				options: [this.listOption('id', 'Workspace (or type its name)', named(this.e().workspaces))],
				callback: (e) => this.engine({ action: 'workspace', id: e.options.id }),
			},
			tournament: {
				name: 'Tournament: open one',
				options: [this.listOption('id', 'Tournament (or type its name)', named(this.e().tournaments))],
				callback: (e) => this.engine({ action: 'tournament', id: e.options.id }),
			},
			// The run of show, the game HUDs, Multistream, the parts.
			control: {
				name: 'Run of show / game HUD / Multistream / app: do it or switch it',
				options: [
					this.listOption('id', 'What', this.controls((c) => c.kind !== 'state')),
					{
						type: 'dropdown',
						id: 'mode',
						label: 'Do (on / off settings only)',
						default: 'toggle',
						choices: MODES,
					},
				],
				callback: (e) => this.send({ do: 'control', id: e.options.id, mode: e.options.mode }),
			},
			ros_go: {
				name: 'Run of show: go to a segment',
				options: [{ ...this.listOption('index', 'Segment', segments, false), default: segments.length ? 0 : '' }],
				callback: (e) => this.send({ do: 'ros_go', index: Number(e.options.index) }),
			},
			value: {
				name: 'Game HUD: set / nudge a value',
				options: [
					this.listOption('id', 'Value', values, false),
					{
						type: 'dropdown',
						id: 'how',
						label: 'Do',
						default: 'adjust',
						choices: [
							{ id: 'adjust', label: 'Nudge by' },
							{ id: 'set', label: 'Set to' },
						],
					},
					{ type: 'number', id: 'value', label: 'Amount', default: 0.1, min: -100, max: 100, step: 0.05 },
				],
				callback: (e) => this.send({ do: 'value', id: e.options.id, how: e.options.how, value: e.options.value }),
			},
		}
	}

	feedbacks() {
		const onBus = (bus) => (fb) => {
			const key = String(fb.options.graphic || '').trim().toLowerCase()
			const g =
				this.graphics().find((g) => g.id === fb.options.graphic) || this.graphics().find((g) => g.name.toLowerCase() === key)
			return !!(g && g[bus])
		}
		const segments = ((this.data && this.data.ros && this.data.ros.segments) || []).map((s) => ({
			id: s.index,
			label: `${s.index + 1}. ${s.title}`,
		}))
		return {
			on_preview: {
				type: 'boolean',
				name: 'GFX: graphic is on Preview',
				defaultStyle: { bgcolor: COLORS.GREEN, color: COLORS.WHITE },
				options: [this.graphicOption()],
				callback: onBus('preview'),
			},
			on_program: {
				type: 'boolean',
				name: 'GFX: graphic is on Program (on air)',
				defaultStyle: { bgcolor: COLORS.RED, color: COLORS.WHITE },
				options: [this.graphicOption()],
				callback: onBus('program'),
			},
			engine_state: {
				type: 'boolean',
				name: 'GFX: something is set (clock mode, best of, loops, casters, a bus not empty)',
				defaultStyle: { bgcolor: COLORS.AMBER, color: COLORS.BLACK },
				options: [{ type: 'dropdown', id: 'state', label: 'While', default: 'program_any', choices: choices(ENGINE_STATES) }],
				callback: (fb) => !!(this.e().states && this.e().states[fb.options.state]),
			},
			control_on: {
				type: 'boolean',
				name: 'Run of show / game HUD / Multistream / app: is on',
				defaultStyle: { bgcolor: COLORS.AMBER, color: COLORS.BLACK },
				options: [this.listOption('id', 'What', this.controls((c) => c.kind !== 'command' || c.on !== null))],
				callback: (fb) => {
					const c = this.data && this.data.controls && this.data.controls[fb.options.id]
					return !!(c && c.on)
				},
			},
			part_status: {
				type: 'boolean',
				name: 'App: a part is running / off / has an error',
				defaultStyle: { bgcolor: COLORS.RED, color: COLORS.WHITE },
				options: [
					this.listOption(
						'part',
						'Part',
						((this.data && this.data.parts) || []).map((p) => ({ id: p.key, label: p.title })),
						false,
					),
					{ type: 'dropdown', id: 'status', label: 'Is', default: 'error', choices: PART_STATUS },
				],
				callback: (fb) => {
					const p = ((this.data && this.data.parts) || []).find((p) => p.key === fb.options.part)
					return !!(p && p.status === fb.options.status)
				},
			},
			ros_on_air: {
				type: 'boolean',
				name: 'Run of show: this segment is on now',
				defaultStyle: { bgcolor: COLORS.RED, color: COLORS.WHITE },
				options: [{ ...this.listOption('index', 'Segment', segments, false), default: segments.length ? 0 : '' }],
				callback: (fb) => !!(this.data && this.data.ros && this.data.ros.current === Number(fb.options.index)),
			},
			disconnected: {
				type: 'boolean',
				name: 'App: not connected',
				description: 'Lights while Companion can’t reach SCC Broadcast Engine',
				defaultStyle: { bgcolor: COLORS.GREY, color: COLORS.WHITE },
				options: [],
				callback: () => this.failed === true,
			},
		}
	}
}

runEntrypoint(BroadcastEngineInstance, [])
