const METRIC_FIELDS = [
  ['testsPassed', 'Passed'],
  ['testsFailed', 'Failed assertions'],
  ['testsSkipped', 'Skipped'],
  ['testsErrored', 'Errors'],
];

export function isVerifiedPass(result) {
  const metrics = result?.metrics;
  const preAssertionFailure = ['application_error', 'test_collection_error', 'test_setup_error']
    .includes(result?.failure_type || result?.diagnosis?.category);
  return result?.status === 'success'
    && result?.defect_detected !== true
    && !preAssertionFailure
    && result?.diagnosis?.endpoint_assertions_ran !== false
    && metrics?.pytestExitCode === 0
    && Number(metrics?.testsCollected) > 0
    && Number(metrics?.testsPassed) > 0
    && Number(metrics?.testsFailed || 0) === 0
    && Number(metrics?.testsErrored || 0) === 0;
}

export function isConfirmedDefect(result) {
  const failureType = result?.failure_type || result?.diagnosis?.category;
  return (result?.status === 'defect_detected' || result?.defect_detected === true)
    && !['application_error', 'test_collection_error', 'test_setup_error'].includes(failureType)
    && result?.diagnosis?.endpoint_assertions_ran !== false
    && Number(result?.metrics?.testsFailed) > 0;
}

export function extractModelInfo(logs = []) {
  const entry = logs.find((log) =>
    String(typeof log === 'string' ? log : log?.message || '').includes('[MODEL]')
  );
  const text = String(typeof entry === 'string' ? entry : entry?.message || '');
  const field = (name) => text.match(new RegExp(`(?:^|\\s)${name}=([^\\s]+)`))?.[1];
  const requested = field('requested_model');
  const returned = field('returned_model');
  if (!requested && !returned) return null;
  return { provider: field('provider'), requested, returned };
}

export function summarizeResult({ status, metrics, diagnosis, failureType, logs = [] }) {
  const model = extractModelInfo(logs);
  const repairAttempts = logs.reduce((max, entry) => {
    const text = String(typeof entry === 'string' ? entry : entry?.message || '');
    const match = text.match(/Repair attempt (\d+)\/(\d+)/i);
    return match ? Math.max(max, Number(match[1])) : max;
  }, 0);

  let title = 'Ready to run';
  let message = 'Generate tests to see the execution summary.';
  if (failureType === 'application_error' || diagnosis?.category === 'application_error') {
    title = diagnosis?.title || 'Application Initialization Error';
    message = diagnosis?.message || 'FastAPI could not initialize the application. Pytest did not collect or execute endpoint assertions.';
  } else if (failureType === 'test_collection_error' || diagnosis?.category === 'test_collection_error') {
    title = diagnosis?.title || 'Test Collection Error';
    message = diagnosis?.message || 'Pytest could not import or collect the test suite; no endpoint assertions ran.';
  } else if (status === 'loading') {
    title = 'Execution in progress';
    message = 'Generating a pytest suite and running it in the isolated sandbox.';
  } else if (status === 'success') {
    title = 'Tests Passed';
    message = `${metrics?.testsPassed ?? 0} passed, ${metrics?.testsFailed ?? 0} failed. Pytest exited with code ${metrics?.pytestExitCode ?? 'unknown'}.`;
  } else if (status === 'defect_detected' && isConfirmedDefect({ status, failureType, diagnosis, metrics })) {
    title = 'Defect Detected';
    message = `${metrics?.testsFailed ?? 0} tests failed, ${metrics?.testsPassed ?? 0} passed. Inspect the failed assertions and endpoint responses.`;
  } else if (failureType === 'no_tests_collected' || diagnosis?.category === 'no_tests_collected') {
    title = 'No Tests Collected';
    message = diagnosis?.message || 'Pytest collected zero tests. This run does not verify API behavior.';
  } else if (failureType === 'all_tests_skipped' || diagnosis?.category === 'all_tests_skipped') {
    title = 'All Tests Were Skipped';
    message = diagnosis?.message || 'Pytest skipped every collected test, so API behavior was not verified.';
  } else if (failureType === 'docker_unavailable' || failureType === 'docker_error' || failureType === 'sandbox_error' || failureType === 'execution_timeout') {
    title = 'Sandbox Error';
    message = diagnosis?.message || 'The Docker sandbox did not complete a valid pytest run.';
  } else if (failureType === 'invalid_generated_tests') {
    title = 'Test Generation Failed';
    message = diagnosis?.message || 'The generated test suite could not be parsed or collected.';
  } else if (failureType === 'test_setup_error') {
    title = 'Test Setup Error';
    message = diagnosis?.message || 'Pytest collected tests but failed during fixture or test setup.';
  } else if (failureType === 'unverified_result') {
    title = 'Run Not Verified';
    message = diagnosis?.message || 'The backend marked this run successful without confirming a passing pytest execution.';
  } else if (status === 'error') {
    title = logs.some((entry) => String(entry).includes('[MODEL]')) ? 'Meta API Error' : 'Execution Error';
    message = diagnosis?.message || 'The request did not produce a verified pytest result.';
  } else if (status === 'defect_detected') {
    title = 'Test Run Inconclusive';
    message = 'No executed failing assertion was available to confirm an API defect.';
  } else if (status === 'failed') {
    title = 'Test Run Inconclusive';
    message = diagnosis?.message || 'The tests did not pass and the available evidence did not confirm an API defect.';
  }

  const counts = METRIC_FIELDS
    .filter(([key]) => metrics?.[key] != null)
    .map(([key, label]) => `${label}: ${metrics[key]}`);
  const details = [];
  if (counts.length) details.push(counts.join(' · '));
  if (metrics?.executionTimeMs != null) details.push(`${metrics.executionTimeMs} ms`);
  if (metrics?.pytestExitCode != null) details.push(`pytest exit ${metrics.pytestExitCode}`);
  if (failureType === 'application_error' || diagnosis?.category === 'application_error') {
    details.push('Execution status: Application initialization failed');
  } else if (failureType === 'test_collection_error' || diagnosis?.category === 'test_collection_error') {
    details.push('Execution status: Test collection failed');
  } else if (status === 'success') {
    details.push('Execution status: Passed');
  } else if (status === 'defect_detected') {
    details.push('Execution status: Defect detected');
  } else if (status === 'error') {
    details.push('Execution status: Infrastructure or generation error');
  }
  if (model) details.push(`Model: ${model.requested || 'unknown'} → ${model.returned || 'unknown'}`);
  if (repairAttempts > 0) details.push(`${repairAttempts} repair attempt${repairAttempts === 1 ? '' : 's'}`);

  const exceptionHeadline = diagnosis?.exception_type
    ? `${diagnosis.exception_type}: ${diagnosis.exception_message || 'Application error'}`
    : null;
  return { title, message, details, model, repairAttempts, exceptionHeadline };
}

export function splitLogEntries(logs = []) {
  const visible = [];
  const raw = [];
  logs.forEach((entry, index) => {
    const message = String(typeof entry === 'string' ? entry : entry?.message || '');
    const isTechnicalOutput = /__TESTFORGE_PYTEST_EXIT_CODE__|<testsuites|<testsuite\b|Traceback \(most recent call last\)|ERROR collecting|FastAPIError:|AssertionError:|During handling of the above exception/i.test(message);
    const target = isTechnicalOutput ? raw : visible;
    target.push({
      id: index,
      message,
      timestamp: typeof entry === 'object' && entry?.timestamp
        ? entry.timestamp
        : new Date().toLocaleTimeString('en-US', { hour12: false }),
    });
  });
  return { visible, raw };
}
