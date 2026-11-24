// What SCC Broadcast Engine can be told to do that doesn't come from the app
// itself. Everything else (graphics, transitions, teams, workspaces, the run of
// show's segments, each game HUD's controls) comes from GET /api/companion,
// so new HUD controls show up without a new module.

// The GFX Engine's quick functions (mirrors apps/gfxengine/gfxengine/companion.py QUICK).
const QUICK = {
	score_left_up: 'Score: left team +1',
	score_left_down: 'Score: left team -1',
	score_right_up: 'Score: right team +1',
	score_right_down: 'Score: right team -1',
	score_reset: 'Score: reset to 0-0',
	swap_sides: 'Teams: swap sides (the game HUDs follow)',
	best_of_1: 'Series: best of 1',
	best_of_3: 'Series: best of 3',
	best_of_5: 'Series: best of 5',
	best_of_7: 'Series: best of 7',
	clock_time: 'Clock: local time',
	clock_soon: 'Clock: Starting Soon countdown',
	clock_brb: 'Clock: Be Right Back countdown',
	timer_toggle: 'Timer: start / pause',
	timer_reset: 'Timer: reset',
	bgloop: 'Background loop: on / off',
	bug_loop: 'Back in bug: live loop behind VS on / off',
	roster_left: 'Player graphics: left team',
	roster_right: 'Player graphics: right team',
	caster_1: 'Casters: 1 box',
	caster_2: 'Casters: 2 boxes',
	caster_3: 'Casters: 3 boxes',
	caster_4: 'Casters: 4 boxes',
}

// The engine's on/off states (lit while they're what's set).
const ENGINE_STATES = {
	preview_any: 'Something is on Preview',
	program_any: 'Something is on Program',
	clock_time: 'Clock is local time',
	clock_soon: 'Clock is Starting Soon',
	clock_brb: 'Clock is Be Right Back',
	timer_toggle: 'Timer is running',
	bgloop: 'Background loop is on',
	bug_loop: 'Back in bug live loop is on',
	roster_left: 'Player graphics show the left team',
	roster_right: 'Player graphics show the right team',
	caster_1: '1 caster box',
	caster_2: '2 caster boxes',
	caster_3: '3 caster boxes',
	caster_4: '4 caster boxes',
	best_of_1: 'Best of 1',
	best_of_3: 'Best of 3',
	best_of_5: 'Best of 5',
	best_of_7: 'Best of 7',
}

// Short button text for the quick functions ($(x) = this connection's variable x).
const QUICK_TEXT = (v) => ({
	score_left_up: `${v('left_short')} +\n${v('left_score')}`,
	score_left_down: `${v('left_short')} −\n${v('left_score')}`,
	score_right_up: `${v('right_short')} +\n${v('right_score')}`,
	score_right_down: `${v('right_short')} −\n${v('right_score')}`,
	score_reset: 'SCORE\n0-0',
	swap_sides: `SWAP\n${v('left_short')} ⇄ ${v('right_short')}`,
	best_of_1: 'BO1',
	best_of_3: 'BO3',
	best_of_5: 'BO5',
	best_of_7: 'BO7',
	clock_time: 'CLOCK\nTime',
	clock_soon: 'CLOCK\nSoon',
	clock_brb: 'CLOCK\nBRB',
	timer_toggle: `TIMER\n${v('timer')}`,
	timer_reset: 'TIMER\nreset',
	bgloop: 'BG\nloop',
	bug_loop: 'BUG\nloop',
	roster_left: `PLAYERS\n${v('left_short')}`,
	roster_right: `PLAYERS\n${v('right_short')}`,
	caster_1: 'CASTERS\n1',
	caster_2: 'CASTERS\n2',
	caster_3: 'CASTERS\n3',
	caster_4: 'CASTERS\n4',
})

// Which quick functions light their button (and the state that lights it).
const QUICK_LIT = Object.keys(QUICK).filter((id) => id in ENGINE_STATES)

const PART_STATUS = [
	{ id: 'on', label: 'Running' },
	{ id: 'starting', label: 'Starting' },
	{ id: 'off', label: 'Off' },
	{ id: 'error', label: 'Error' },
]

const choices = (obj) => Object.entries(obj).map(([id, label]) => ({ id, label }))

module.exports = { QUICK, ENGINE_STATES, QUICK_TEXT, QUICK_LIT, PART_STATUS, choices }
