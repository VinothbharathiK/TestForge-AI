import asyncio
import json
from pathlib import Path
from unittest.mock import Mock, patch

import docker

from backend.sandbox import ExecutionSandbox, RESULT_MARKER


def xml_output(exit_code, xml):
    return f"__TESTFORGE_PYTEST_EXIT_CODE__={exit_code}\n{xml}".encode()


class FakeContainer:
    def __init__(self, output, exit_code=0, status="exited"):
        self.output = output
        self.status = status
        self.attrs = {"State": {"ExitCode": exit_code}}
        self.removed = False
        self.stopped = False

    def reload(self):
        return None

    def logs(self, stdout=True, stderr=True):
        return self.output

    def stop(self, timeout=2):
        self.stopped = True
        self.status = "exited"

    def kill(self):
        self.status = "exited"

    def remove(self, force=True):
        self.removed = True


class FakeDockerClient:
    def __init__(self, container):
        self.container = container
        self.images = Mock()
        self.images.get.return_value = object()
        self.containers = Mock()
        self.containers.run.side_effect = self.run
        self.run_kwargs = None
        self.closed = False

    def run(self, *args, **kwargs):
        self.run_kwargs = kwargs
        return self.container

    def close(self):
        self.closed = True

    def ping(self):
        return True


def parse_result(logs):
    marker_index = logs.rfind(RESULT_MARKER)
    assert marker_index >= 0
    return json.loads(logs[marker_index + len(RESULT_MARKER) :])


def test_pytest_pass_requires_nonzero_collection_and_real_exit_zero():
    report = (
        '<testsuites tests="2" failures="0" errors="0" skipped="0">'
        '<testsuite tests="2" failures="0" errors="0" skipped="0">'
        '<testcase/><testcase/></testsuite></testsuites>'
    )
    container = FakeContainer(xml_output(0, report))
    client = FakeDockerClient(container)
    sandbox = ExecutionSandbox(timeout_seconds=2)

    with patch("backend.sandbox.docker.from_env", return_value=client):
        passed, logs = asyncio.run(
            sandbox.run_test_in_docker("def test_one(): assert True", "app = None")
        )

    result = parse_result(logs)
    assert passed is True
    assert result["exit_code"] == 0
    assert result["collected"] == 2
    assert result["passed"] == 2
    assert container.removed is True
    assert client.closed is True
    mount = client.run_kwargs["volumes"]
    workspace = Path(next(iter(mount)))
    assert not workspace.exists()


def test_pytest_assertion_failure_is_returned_as_failure_with_counts():
    report = (
        '<testsuites tests="1" failures="1" errors="0" skipped="0">'
        '<testsuite tests="1" failures="1" errors="0" skipped="0">'
        '<testcase><failure message="expected 400">AssertionError</failure>'
        '</testcase></testsuite></testsuites>'
    )
    client = FakeDockerClient(FakeContainer(xml_output(1, report), exit_code=1))
    sandbox = ExecutionSandbox(timeout_seconds=2)

    with patch("backend.sandbox.docker.from_env", return_value=client):
        passed, logs = asyncio.run(
            sandbox.run_test_in_docker("def test_one(): assert False", "app = None")
        )

    result = parse_result(logs)
    assert passed is False
    assert result["error_type"] == "assertion_failure"
    assert result["failures"] == 1
    assert result["passed"] == 0


def test_zero_collected_tests_is_never_success():
    report = (
        '<testsuites tests="0" failures="0" errors="0" skipped="0">'
        '<testsuite tests="0" failures="0" errors="0" skipped="0">'
        '</testsuite></testsuites>'
    )
    client = FakeDockerClient(FakeContainer(xml_output(5, report), exit_code=5))
    sandbox = ExecutionSandbox(timeout_seconds=2)

    with patch("backend.sandbox.docker.from_env", return_value=client):
        passed, logs = asyncio.run(
            sandbox.run_test_in_docker("", "app = None")
        )

    result = parse_result(logs)
    assert passed is False
    assert result["collected"] == 0
    assert result["error_type"] == "no_tests_collected"
    assert result["diagnosis"]["category"] == "no_tests_collected"


def test_fastapi_error_for_non_pydantic_route_model_is_application_initialization_error():
    report = (
        '<testsuites tests="1" failures="0" errors="1" skipped="0">'
        '<testsuite tests="1" failures="0" errors="1" skipped="0">'
        '<testcase><error type="FastAPIError" message="Invalid args for response field">'
        'FastAPIError: Invalid args for response field</error></testcase>'
        '</testsuite></testsuites>'
    )
    output = (
        b"ERROR collecting test_app.py\n"
        b"fastapi.exceptions.FastAPIError: Invalid args for response field!\n"
        b"__TESTFORGE_PYTEST_EXIT_CODE__=2\n"
        + report.encode()
    )
    client = FakeDockerClient(FakeContainer(output, exit_code=2))
    sandbox = ExecutionSandbox(timeout_seconds=2)
    route_code = (
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "class RegistrationRequest():\n"
        "    username: str\n"
        "@app.post('/register')\n"
        "def register_user(user: RegistrationRequest):\n"
        "    return {'username': user.username}\n"
    )

    with patch("backend.sandbox.docker.from_env", return_value=client):
        passed, logs = asyncio.run(
            sandbox.run_test_in_docker("from fastapi.testclient import TestClient", route_code)
        )

    result = parse_result(logs)
    diagnosis = result["diagnosis"]
    assert passed is False
    assert result["exit_code"] == 2
    assert result["error_type"] == "application_error"
    assert result["collected"] == 0
    assert result["passed"] == 0
    assert result["failures"] == 0
    assert result["errors"] == 1
    assert diagnosis["category"] == "application_error"
    assert diagnosis["title"] == "Application Initialization Error"
    assert diagnosis["endpoint_assertions_ran"] is False
    assert "RegistrationRequest" in diagnosis["likely_cause"]
    assert "BaseModel" in diagnosis["suggestion"]
    assert "username: str" in diagnosis["suggestion"]
    assert "no endpoint assertions were executed" in diagnosis["message"]
    assert diagnosis["exception_type"] == "FastAPIError"
    assert diagnosis["exception_message"] == "Invalid args for response field!"
    assert client.container.removed is True
    assert client.closed is True


def test_collection_error_with_junit_test_error_is_not_counted_as_executed_test():
    report = (
        '<testsuites tests="1" failures="0" errors="1" skipped="0">'
        '<testsuite tests="1" failures="0" errors="1" skipped="0">'
        '<testcase><error type="ImportError">ImportError</error></testcase>'
        '</testsuite></testsuites>'
    )
    output = (
        b"ERROR collecting test_app.py\nImportError while importing test module\n"
        b"__TESTFORGE_PYTEST_EXIT_CODE__=2\n" + report.encode()
    )
    client = FakeDockerClient(FakeContainer(output, exit_code=2))
    sandbox = ExecutionSandbox(timeout_seconds=2)

    with patch("backend.sandbox.docker.from_env", return_value=client):
        passed, logs = asyncio.run(
            sandbox.run_test_in_docker("def test_one(): assert True", "app = None")
        )

    result = parse_result(logs)
    assert passed is False
    assert result["error_type"] == "test_collection_error"
    assert result["exit_code"] == 2
    assert result["collected"] == 0
    assert result["passed"] == 0
    assert result["failures"] == 0
    assert result["errors"] == 1
    assert result["diagnosis"]["endpoint_assertions_ran"] is False


def test_fixture_setup_error_stays_distinct_from_collection_and_assertion_errors():
    report = (
        '<testsuites tests="1" failures="0" errors="1" skipped="0">'
        '<testsuite tests="1" failures="0" errors="1" skipped="0">'
        '<testcase><error type="FixtureLookupError">fixture error</error></testcase>'
        '</testsuite></testsuites>'
    )
    output = (
        b"ERROR at setup of test_health\nfixture 'client' not found\n"
        b"__TESTFORGE_PYTEST_EXIT_CODE__=1\n" + report.encode()
    )
    client = FakeDockerClient(FakeContainer(output, exit_code=1))
    sandbox = ExecutionSandbox(timeout_seconds=2)

    with patch("backend.sandbox.docker.from_env", return_value=client):
        passed, logs = asyncio.run(
            sandbox.run_test_in_docker("def test_health(client): assert True", "app = None")
        )

    result = parse_result(logs)
    assert passed is False
    assert result["error_type"] == "test_setup_error"
    assert result["collected"] == 1
    assert result["failures"] == 0
    assert result["errors"] == 1
    assert result["diagnosis"]["endpoint_assertions_ran"] is False


def test_all_skipped_tests_have_distinct_non_passing_classification():
    report = (
        '<testsuites tests="2" failures="0" errors="0" skipped="2">'
        '<testsuite tests="2" failures="0" errors="0" skipped="2">'
        '<testcase><skipped/></testcase><testcase><skipped/></testcase>'
        '</testsuite></testsuites>'
    )
    client = FakeDockerClient(FakeContainer(xml_output(0, report)))
    sandbox = ExecutionSandbox(timeout_seconds=2)

    with patch("backend.sandbox.docker.from_env", return_value=client):
        passed, logs = asyncio.run(
            sandbox.run_test_in_docker("def test_one(): pass", "app = None")
        )

    result = parse_result(logs)
    assert passed is False
    assert result["error_type"] == "all_tests_skipped"


def test_docker_unavailable_returns_explicit_error_without_host_execution():
    sandbox = ExecutionSandbox(timeout_seconds=2)
    with patch(
        "backend.sandbox.docker.from_env",
        side_effect=docker.errors.DockerException("daemon unavailable"),
    ):
        passed, logs = asyncio.run(
            sandbox.run_test_in_docker("def test_one(): pass", "app = None")
        )

    result = parse_result(logs)
    assert passed is False
    assert result["error_type"] == "docker_unavailable"
    assert "Docker is unavailable" in logs


def test_execution_timeout_stops_and_removes_container():
    report = '<testsuites tests="0" failures="0" errors="0" skipped="0"></testsuites>'
    container = FakeContainer(xml_output(137, report), exit_code=137, status="running")
    client = FakeDockerClient(container)
    sandbox = ExecutionSandbox(timeout_seconds=0.01)

    with patch("backend.sandbox.docker.from_env", return_value=client):
        passed, logs = asyncio.run(
            sandbox.run_test_in_docker("def test_one(): pass", "app = None")
        )

    result = parse_result(logs)
    assert passed is False
    assert result["timed_out"] is True
    assert container.stopped is True
    assert container.removed is True
