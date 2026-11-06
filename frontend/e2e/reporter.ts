import type { FullResult, Reporter, TestCase, TestResult, TestStep } from '@playwright/test/reporter'
/** No traces, DOM snapshots, request bodies, locators with values, or raw errors. */
export default class SafeReporter implements Reporter {
  private passed = 0
  private failed = 0
  private skipped = 0
  private steps = new Map<string, string>()
  onStepEnd(test: TestCase, _result: TestResult, step: TestStep) {
    if (step.error && step.category === 'test.step') this.steps.set(test.id, step.title)
  }
  onTestEnd(test: TestCase, result: TestResult) {
    if (result.status === 'passed') this.passed++
    else if (result.status === 'skipped') this.skipped++
    else this.failed++
    process.stdout.write(result.status.toUpperCase() + ': ' + test.title + '\n')
    if (result.status !== 'passed' && result.status !== 'skipped') {
      const stateDiagnostic = test.annotations.find(item => item.type === 'qa-state')
      if (stateDiagnostic?.description) {
        const state = JSON.parse(stateDiagnostic.description) as Record<string, unknown>
        process.stdout.write('  QA state: ' + JSON.stringify({ loading: Number(state.loading), visibleLoading: Number(state.visibleLoading), reviewButtons: Number(state.reviewButtons) }) + '\n')
      }
      const failure = result.error?.message || ''
      process.stdout.write('  Failure category: ' + (failure.includes('strict mode violation') ? 'ambiguous accessible selector' : failure.includes('Timeout') || failure.includes('timeout') ? 'timeout' : 'assertion') + '\n')
      const overflow = test.annotations.find(item => item.type === 'qa-overflow')
      if (overflow?.description) {
        const rows = JSON.parse(overflow.description) as { tag: string; className: string; width: number }[]
        process.stdout.write('  Overflow components: ' + rows.filter(row => /^[A-Z]+$/.test(row.tag) && /^[a-zA-Z0-9_ -]*$/.test(row.className)).map(row => row.tag + '.' + row.className + ':' + Number(row.width)).join(', ') + '\n')
      }
      const rules = test.annotations.find(item => item.type === 'qa-rules')
      if (rules?.description) {
        const list = JSON.parse(rules.description) as { id: string; nodes: number }[]
        process.stdout.write('  Accessibility rules: ' + list.filter(row => /^[a-z-]+$/.test(row.id)).map(row => row.id + ':' + Number(row.nodes)).join(', ') + '\n')
      }
      const diagnostic = test.annotations.find(annotation => annotation.type === 'share-state')
      if (diagnostic?.description) {
        const state = JSON.parse(diagnostic.description) as Record<string, unknown>
        process.stdout.write('  Share state: ' + JSON.stringify({ hasFragment: state.hasFragment === true, unavailable: state.unavailable === true, checking: state.checking === true, resolutions: Number(state.resolutions) || 0 }) + '\n')
      }
      const line = result.error?.location?.line ?? test.location.line
      process.stdout.write('  Failed step: ' + (this.steps.get(test.id) || 'browser journey') + '; source line ' + line + '. Raw credential-bearing diagnostics are suppressed.\n')
    }
  }
  onError() { process.stderr.write('Browser runner failed before a journey completed; check installed Chrome and the guarded stack configuration.\n') }
  onEnd(result: FullResult) {
    process.stdout.write('Browser verification: ' + this.passed + ' passed, ' + this.failed + ' failed, ' + this.skipped + ' skipped; ' + result.status + '.\n')
  }
}
