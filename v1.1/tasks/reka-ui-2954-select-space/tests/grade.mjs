// Usage: node grade.mjs <config.json> <vitest.json> <log-dir>
// Writes statuses.json, report.json and reward.txt to <log-dir>.
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { join, relative } from 'node:path'

const [configPath, resultsPath, logDir] = process.argv.slice(2)
const config = JSON.parse(readFileSync(configPath, 'utf8'))

// A test id is "<repo-relative file> > <describe> > ... > <it>". The same id can
// appear more than once (duplicate titles), so it passes only if every run passed.
const statuses = {}
let error = null

if (existsSync(resultsPath)) {
  const results = JSON.parse(readFileSync(resultsPath, 'utf8'))
  for (const file of results.testResults ?? []) {
    const path = relative(config.repo_root, file.name)
    for (const assertion of file.assertionResults ?? []) {
      const id = [path, ...assertion.ancestorTitles, assertion.title].join(' > ')
      statuses[id] = assertion.status === 'passed' && statuses[id] !== false
    }
  }
}
else {
  error = `Vitest results not found at ${resultsPath}`
}

function partition(ids) {
  return {
    success: ids.filter(id => statuses[id] === true),
    failure: ids.filter(id => statuses[id] !== true),
  }
}

const failToPass = partition(config.fail_to_pass)
const passToPass = partition(config.pass_to_pass)
const resolved = error === null
  && config.fail_to_pass.length > 0
  && failToPass.failure.length === 0
  && passToPass.failure.length === 0

const report = {
  task_id: config.task_id,
  resolved,
  error,
  fail_to_pass: failToPass,
  pass_to_pass: passToPass,
}

writeFileSync(join(logDir, 'statuses.json'), `${JSON.stringify(statuses, null, 2)}\n`)
writeFileSync(join(logDir, 'report.json'), `${JSON.stringify(report, null, 2)}\n`)
writeFileSync(join(logDir, 'reward.txt'), resolved ? '1\n' : '0\n')

console.log(`FAIL_TO_PASS: ${failToPass.success.length}/${config.fail_to_pass.length} passed`)
console.log(`PASS_TO_PASS: ${passToPass.success.length}/${config.pass_to_pass.length} passed`)
for (const id of [...failToPass.failure, ...passToPass.failure])
  console.log(`  FAILED: ${id}`)
console.log(`resolved: ${resolved}`)
