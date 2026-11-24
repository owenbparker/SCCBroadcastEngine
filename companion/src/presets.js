// Ready-made buttons (the Presets tab), made from what the app has now: one per
// graphic, transition, team, workspace, tournament, run of show segment and
// game HUD control. They're made again when any of those change.

const { combineRgb } = require('@companion-module/base')
const { QUICK, QUICK_TEXT, QUICK_LIT } = require('./definitions')

const COLORS = {
	GREEN: combineRgb(0, 178, 72),
	RED: combineRgb(214, 32, 32),
	AMBER: combineRgb(245, 197, 24),
	BLUE: combineRgb(10, 100, 200),
	GREY: combineRgb(90, 90, 90),
	DARK: combineRgb(20, 22, 25),
	WHITE: combineRgb(255, 255, 255),
	BLACK: combineRgb(0, 0, 0),
}

// Each group's short name on a button.
const ABBR = {
	'Run of show': 'ROS',
	'League of Legends': 'LOL',
	VALORANT: 'VAL',
	'Call of Duty': 'COD',
	'Rocket League': 'RL',
	'Smash Ultimate': 'SMASH',
	Overwatch: 'OW',
	Multistream: 'STREAM',
	Parts: 'APP',
}

// "Timeout: left team calls one (uses one up)" -> "Timeout: left team calls one"
function shortText(label) {
	return label
		.replace(/\s*\([^)]*\)/g, '')
		.replace(/^Run of show: /, '')
		.trim()
}

function buildPresets(self) {
	const presets = {}
	const v = (name) => `$(${self.label}:${name})`
	const button = (category, name, text, down, feedbacks = [], size = 'auto') => ({
		type: 'button',
		category,
		name,
		style: { text, size, color: COLORS.WHITE, bgcolor: COLORS.DARK },
		steps: [{ down, up: [] }],
		feedbacks,
	})
	const lit = (feedbackId, options, bgcolor, color = COLORS.WHITE) => ({ feedbackId, options, style: { bgcolor, color } })
	const e = self.e()
	const data = self.data || {}

	// --- GFX: one Preview and one Program button per graphic.
	for (const g of e.graphics || []) {
		presets[`pvw_${g.id}`] = button(
			'GFX: Preview',
			`${g.name}: Preview on / off`,
			g.name,
			[{ actionId: 'preview', options: { graphic: g.id, mode: 'toggle' } }],
			[lit('on_preview', { graphic: g.id }, COLORS.GREEN)],
		)
		presets[`pgm_${g.id}`] = button(
			'GFX: Program',
			`${g.name}: in / out on Program`,
			g.name,
			[{ actionId: 'program', options: { graphic: g.id, mode: 'toggle', transition: '' } }],
			[lit('on_program', { graphic: g.id }, COLORS.RED)],
		)
	}

	// --- GFX: take (each transition, stingers included), clear, update.
	const busLit = (state, bgcolor) => [lit('engine_state', { state }, bgcolor)]
	presets.take = button(
		'GFX: Take',
		'Take (the default transition)',
		`TAKE\n${v('default_transition')}`,
		[{ actionId: 'take', options: { transition: '' } }],
		busLit('preview_any', COLORS.GREEN),
	)
	for (const t of e.transitions || []) {
		presets[`take_${t.id}`] = button(
			'GFX: Take',
			`Take: ${t.name}`,
			`TAKE\n${t.name}`,
			[{ actionId: 'take', options: { transition: t.id } }],
			busLit('preview_any', COLORS.GREEN),
		)
	}
	presets.clear_program = button(
		'GFX: Take',
		'Clear Program',
		'CLEAR\nPGM',
		[{ actionId: 'clear', options: { bus: 'program', transition: '' } }],
		busLit('program_any', COLORS.RED),
	)
	presets.clear_preview = button(
		'GFX: Take',
		'Clear Preview',
		'CLEAR\nPVW',
		[{ actionId: 'clear', options: { bus: 'preview', transition: '' } }],
		busLit('preview_any', COLORS.GREEN),
	)
	presets.clear_both = button('GFX: Take', 'Clear Program and Preview', 'CLEAR\nALL', [
		{ actionId: 'clear', options: { bus: 'both', transition: '' } },
	])
	presets.send = button('GFX: Take', 'Update Program (Preview values to air)', 'UPDATE\nPGM', [
		{ actionId: 'send', options: { graphic: '' } },
	])
	presets.on_air = button('GFX: Take', 'On air now (shows what is on Program)', `PGM\n${v('program')}`, [], [], '7')
	presets.on_pvw = button('GFX: Take', 'On Preview now', `PVW\n${v('preview')}`, [], [], '7')

	// --- GFX: quick functions (score, series, clock, timer...).
	const text = QUICK_TEXT(v)
	for (const [id, name] of Object.entries(QUICK)) {
		const cat = /^(Score|Teams|Series):/.test(name) ? 'Score, series & teams' : 'GFX: Quick functions'
		presets[`quick_${id}`] = button(
			cat,
			name,
			text[id] || name,
			[{ actionId: 'quick', options: { quick: id } }],
			QUICK_LIT.includes(id) ? [lit('engine_state', { state: id }, COLORS.AMBER, COLORS.BLACK)] : [],
		)
	}
	presets.series = button(
		'Score, series & teams',
		'The series score (display)',
		`${v('left_short')} ${v('left_score')}-${v('right_score')} ${v('right_short')}\nBO${v('best_of')} · G${v('game_number')}`,
		[],
		[],
		'14',
	)

	// --- Teams from the team list (both sides), workspaces, tournaments.
	for (const [i, t] of (e.teams || []).slice(0, 64).entries()) {
		const key = t.game ? `${t.name}|${t.game}` : t.name
		for (const side of ['left', 'right']) {
			presets[`team_${side}_${i}`] = button(
				`Teams: ${side} side`,
				`${t.name}${t.game ? ` (${t.game})` : ''} on the ${side}`,
				`${side === 'left' ? '◀' : '▶'} ${t.name}`,
				[{ actionId: 'team', options: { side, team: key } }],
			)
		}
	}
	for (const w of e.workspaces || []) {
		presets[`ws_${w.id}`] = button('Workspaces & tournaments', `Open the workspace ${w.name}`, `WS\n${w.name}`, [
			{ actionId: 'workspace', options: { id: w.id } },
		])
	}
	for (const t of e.tournaments || []) {
		presets[`tour_${t.id}`] = button('Workspaces & tournaments', `Open the tournament ${t.name}`, `EVENT\n${t.name}`, [
			{ actionId: 'tournament', options: { id: t.id } },
		])
	}

	// --- Run of show.
	const controlButton = (cat, id, c, txt) => {
		const fb = []
		if (c.kind === 'toggle') fb.push(lit('control_on', { id }, COLORS.AMBER, COLORS.BLACK))
		if (c.kind === 'command' && c.on !== null) fb.push(lit('control_on', { id }, COLORS.AMBER, COLORS.BLACK))
		if (c.kind === 'state') fb.push(lit('control_on', { id }, COLORS.RED))
		return button(
			cat,
			c.label,
			txt,
			c.kind === 'state' ? [] : [{ actionId: 'control', options: { id, mode: 'toggle' } }],
			fb,
		)
	}
	const controls = data.controls || {}
	const rosText = {
		'ros.next': `NEXT ▶\n${v('ros_next')}`,
		'ros.prev': '◀ BACK',
		'ros.reset': 'ROS\nreset',
		'ros.cue': 'CUE\nsegment GFX',
		'ros.auto': 'ROS\nauto',
	}
	for (const [id, c] of Object.entries(controls)) {
		if (c.group === 'Run of show') presets[`c_${id}`] = controlButton('Run of show', id, c, rosText[id] || shortText(c.label))
	}
	presets.ros_now = button(
		'Run of show',
		'On now (segment and time left)',
		`NOW ${v('ros_position')}\n${v('ros_current')}\n${v('ros_left')}`,
		[],
		[],
		'14',
	)
	presets.ros_next_info = button('Run of show', 'Next (and when)', `NEXT ${v('ros_next_at')}\n${v('ros_next')}`, [], [], '14')
	for (const s of (data.ros && data.ros.segments) || []) {
		presets[`ros_go_${s.index}`] = button(
			'Run of show: segments',
			`Go to ${s.index + 1}. ${s.title}`,
			`${s.index + 1}\n${s.title}`,
			[{ actionId: 'ros_go', options: { index: s.index } }],
			[lit('ros_on_air', { index: s.index }, COLORS.RED)],
		)
	}

	// --- Each game HUD, Multistream and the parts: one button per control.
	for (const [id, c] of Object.entries(controls)) {
		if (c.group === 'Run of show') continue
		const abbr = ABBR[c.group] || c.group.toUpperCase()
		let label = shortText(c.label)
		if (c.group === 'Parts') label = label.replace(/: running.*$/, '').replace(/: restart$/, ' ↻')
		presets[`c_${id}`] = controlButton(c.group === 'Parts' ? 'App: parts' : c.group, id, c, `${abbr}\n${label}`)
	}
	for (const [id, val] of Object.entries(data.values || {})) {
		const step = Math.max(0.05, Math.round(((val.max - val.min) / 20) * 100) / 100)
		const abbr = ABBR[val.group] || val.group
		const label = shortText(val.label).replace(/^.*: /, '')
		presets[`v_${id}_up`] = button(val.group, `${val.label}: up`, `${abbr}\n${label} +`, [
			{ actionId: 'value', options: { id, how: 'adjust', value: step } },
		])
		presets[`v_${id}_down`] = button(val.group, `${val.label}: down`, `${abbr}\n${label} −`, [
			{ actionId: 'value', options: { id, how: 'adjust', value: -step } },
		])
	}

	// --- Is it connected?
	presets.status = button('App: parts', 'Connected? (grey when Companion can’t reach the app)', 'SCC BE\n$(' + self.label + ':app_version)', [], [
		{ feedbackId: 'disconnected', options: {}, style: { bgcolor: COLORS.GREY, color: COLORS.WHITE, text: 'SCC BE\noffline' } },
	])
	return presets
}

module.exports = { buildPresets, COLORS, shortText }
