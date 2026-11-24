// node tools/stamp.js 1.0.190: the release's version into package.json and the manifest.
const fs = require('fs')
const path = require('path')
const v = process.argv[2]
if (!/^\d+\.\d+\.\d+$/.test(v || '')) {
	console.error('Usage: node tools/stamp.js 1.0.190')
	process.exit(1)
}
for (const f of ['package.json', 'companion/manifest.json']) {
	const p = path.join(__dirname, '..', f)
	const j = JSON.parse(fs.readFileSync(p, 'utf8'))
	j.version = v
	fs.writeFileSync(p, JSON.stringify(j, null, '\t') + '\n')
	console.log(`${f}: ${v}`)
}
