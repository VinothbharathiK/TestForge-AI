import assert from 'node:assert/strict';
import test from 'node:test';
import { isConfirmedDefect, isVerifiedPass, splitLogEntries, summarizeResult } from './resultPresentation.js';

test('frontend accepts green success only with real passing pytest metrics', () => {
  const verified = {
    status: 'success',
    metrics: {
      pytestExitCode: 0,
      testsCollected: 1,
      testsPassed: 1,
      testsFailed: 0,
      testsErrored: 0,
    },
  };
  assert.equal(isVerifiedPass(verified), true);
  assert.equal(isVerifiedPass({ ...verified, metrics: { ...verified.metrics, testsCollected: 0, testsPassed: 0 } }), false);
  assert.equal(isVerifiedPass({ ...verified, metrics: { ...verified.metrics, pytestExitCode: 5 } }), false);
  assert.equal(isVerifiedPass({ ...verified, metrics: { ...verified.metrics, testsFailed: 1 } }), false);
  assert.equal(isVerifiedPass({ status: 'success', metrics: null }), false);
});

test('successful result summary uses actual pytest counts and exit code', () => {
  const summary = summarizeResult({
    status: 'success',
    metrics: {
      testsPassed: 13,
      testsFailed: 0,
      testsSkipped: 0,
      testsErrored: 0,
      pytestExitCode: 0,
      executionTimeMs: 824,
    },
  });

  assert.equal(summary.title, 'Tests Passed');
  assert.match(summary.message, /13 passed, 0 failed/);
  assert.match(summary.message, /code 0/);
  assert.ok(summary.details.includes('824 ms'));
});

test('FastAPI initialization diagnosis is distinct from endpoint defect', () => {
  const summary = summarizeResult({
    status: 'failed',
    failureType: 'application_error',
    diagnosis: {
      category: 'application_error',
      title: 'Application Initialization Error',
      message: 'FastAPI could not initialize because the RegistrationRequest declaration is not a valid Pydantic request model. Pytest could not collect the tests, so no endpoint assertions were executed.',
      suggestion: 'class RegistrationRequest(BaseModel):',
      exception_type: 'FastAPIError',
      exception_message: 'Invalid args for response field!',
      endpoint_assertions_ran: false,
    },
    metrics: {
      pytestExitCode: 2,
      testsCollected: 0,
      testsPassed: 0,
      testsFailed: 0,
      testsSkipped: 0,
      testsErrored: 1,
    },
  });

  assert.equal(summary.title, 'Application Initialization Error');
  assert.match(summary.message, /no endpoint assertions were executed/);
  assert.equal(summary.exceptionHeadline, 'FastAPIError: Invalid args for response field!');
  assert.ok(summary.details.includes('Passed: 0 · Failed assertions: 0 · Skipped: 0 · Errors: 1'));
  assert.ok(summary.details.includes('pytest exit 2'));
  assert.ok(summary.details.includes('Execution status: Application initialization failed'));
  assert.notEqual(summary.title, 'Defect Detected');
});

test('collection error evidence takes priority over a stale defect label', () => {
  const summary = summarizeResult({
    status: 'defect_detected',
    failureType: 'test_collection_error',
    diagnosis: {
      category: 'test_collection_error',
      title: 'Test Collection Error',
      message: 'Pytest failed before endpoint assertions ran.',
      endpoint_assertions_ran: false,
    },
    metrics: { testsCollected: 0, testsFailed: 0, testsErrored: 1, pytestExitCode: 2 },
  });

  assert.equal(summary.title, 'Test Collection Error');
  assert.notEqual(summary.title, 'Defect Detected');
  assert.equal(isConfirmedDefect({
    status: 'defect_detected',
    failure_type: 'test_collection_error',
    diagnosis: { category: 'test_collection_error', endpoint_assertions_ran: false },
    metrics: { testsFailed: 0 },
  }), false);
});

test('only an executed assertion failure can produce a confirmed defect', () => {
  const verifiedDefect = {
    status: 'defect_detected',
    defect_detected: true,
    failure_type: 'assertion_failure',
    diagnosis: { endpoint_assertions_ran: true },
    metrics: { testsCollected: 2, testsPassed: 1, testsFailed: 1, testsErrored: 0, pytestExitCode: 1 },
  };

  assert.equal(isConfirmedDefect(verifiedDefect), true);
  assert.equal(isConfirmedDefect({
    ...verifiedDefect,
    failure_type: 'inconclusive',
  }), false);
});

test('zero tests and all-skipped suites stay non-passing and distinct', () => {
  const zeroTests = summarizeResult({
    status: 'failed',
    failureType: 'no_tests_collected',
    metrics: { testsCollected: 0, testsPassed: 0, testsFailed: 0, testsErrored: 0, pytestExitCode: 5 },
  });
  const skipped = summarizeResult({
    status: 'failed',
    failureType: 'all_tests_skipped',
    metrics: { testsCollected: 2, testsPassed: 0, testsSkipped: 2, testsFailed: 0, testsErrored: 0, pytestExitCode: 0 },
  });

  assert.equal(zeroTests.title, 'No Tests Collected');
  assert.equal(skipped.title, 'All Tests Were Skipped');
  assert.equal(isVerifiedPass({ status: 'success', metrics: { pytestExitCode: 0, testsCollected: 2, testsPassed: 0, testsFailed: 0, testsErrored: 0 } }), false);
});

test('test setup and sandbox errors have separate neutral summaries', () => {
  assert.equal(summarizeResult({ status: 'failed', failureType: 'test_setup_error' }).title, 'Test Setup Error');
  assert.equal(summarizeResult({ status: 'error', failureType: 'docker_unavailable' }).title, 'Sandbox Error');
});

test('inconclusive and unknown statuses never render as verified passes', () => {
  const summary = summarizeResult({
    status: 'failed',
    failureType: 'inconclusive',
    diagnosis: {
      category: 'inconclusive',
      message: 'Pytest reported an execution error without enough evidence.',
    },
  });

  assert.equal(summary.title, 'Test Run Inconclusive');
  assert.match(summary.message, /without enough evidence/);
  assert.equal(isVerifiedPass({ status: 'inconclusive', metrics: { pytestExitCode: 0, testsCollected: 1, testsPassed: 1 } }), false);
  assert.equal(isVerifiedPass({ status: 'unexpected', metrics: { pytestExitCode: 0, testsCollected: 1, testsPassed: 1 } }), false);
  assert.equal(isVerifiedPass({ status: 'success', failure_type: 'unknown', metrics: { pytestExitCode: 0, testsCollected: 1, testsPassed: 1 } }), false);
});

test('raw pytest/XML output is hidden from the concise log stream but retained', () => {
  const logs = [
    '[AGENT] Connecting to Meta',
    'FastAPIError: Invalid args for response field!\n<testsuites tests="0">',
  ];
  const split = splitLogEntries(logs);

  assert.equal(split.visible.length, 1);
  assert.equal(split.raw.length, 1);
  assert.match(split.raw[0].message, /<testsuites/);
  assert.ok(split.visible[0].timestamp);
});

test('model request and returned IDs are included when backend provides them', () => {
  const summary = summarizeResult({
    status: 'success',
    logs: [
      '[MODEL] provider=meta_model_api requested_model=muse-spark-1.3 returned_model=muse-spark-1.3 request_id=req-123 outcome=success',
    ],
  });

  assert.ok(summary.details.includes('Model: muse-spark-1.3 → muse-spark-1.3'));
});
