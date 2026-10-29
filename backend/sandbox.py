"""Disposable Docker execution for generated pytest suites."""

from __future__ import annotations

import asyncio
import ast
import json
import os
import re
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from threading import Lock
from typing import Any

import docker
from docker.errors import DockerException, ImageNotFound


RESULT_MARKER = "__TESTFORGE_RESULT_JSON__="
RUNNER_IMAGE = "testforge-pytest-runner:py311-v2"
MAX_LOG_BYTES = 64_000
_IMAGE_BUILD_LOCK = Lock()


class ExecutionSandbox:
    """Run API source and generated tests in a constrained container."""

    def __init__(
        self,
        *,
        timeout_seconds: int | None = None,
        memory_limit: str | None = None,
        nano_cpus: int | None = None,
        pids_limit: int | None = None,
        image: str = RUNNER_IMAGE,
    ) -> None:
        self.timeout_seconds = timeout_seconds or int(
            os.environ.get("TESTFORGE_DOCKER_TIMEOUT_SECONDS", "60")
        )
        self.memory_limit = memory_limit or os.environ.get(
            "TESTFORGE_DOCKER_MEMORY_LIMIT", "512m"
        )
        self.nano_cpus = nano_cpus or int(
            os.environ.get("TESTFORGE_DOCKER_NANO_CPUS", "1000000000")
        )
        self.pids_limit = pids_limit or int(
            os.environ.get("TESTFORGE_DOCKER_PIDS_LIMIT", "64")
        )
        self.image = image

        if self.timeout_seconds <= 0 or self.nano_cpus <= 0 or self.pids_limit <= 0:
            raise ValueError("Docker timeout, CPU limit, and process limit must be positive.")

    async def run_test_in_docker(
        self, test_code: str, route_code: str
    ) -> tuple[bool, str]:
        """Return (passed, logs); Docker unavailability is reported as an error."""
        started = time.monotonic()
        try:
            with tempfile.TemporaryDirectory(prefix="testforge-run-") as temp_dir:
                workspace = Path(temp_dir)
                app_path = workspace / "main.py"
                test_path = workspace / "test_app.py"
                app_path.write_text(route_code, encoding="utf-8")
                test_path.write_text(test_code, encoding="utf-8")

                # Files are read-only in the container and readable by its
                # unprivileged user, including on Docker Desktop bind mounts.
                os.chmod(workspace, 0o755)
                os.chmod(app_path, 0o644)
                os.chmod(test_path, 0o644)

                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(
                    None, self._run_container_sync, temp_dir, started
                )
        except OSError as exc:
            return False, self._encode_result(
                f"Sandbox workspace error: {exc}",
                {
                    "error_type": "sandbox_error",
                    "duration_seconds": round(time.monotonic() - started, 3),
                },
            )

    def _run_container_sync(self, workspace: str, started: float) -> tuple[bool, str]:
        client = None
        try:
            client = docker.from_env(timeout=120)
            client.ping()
        except DockerException as exc:
            if client is not None:
                try:
                    client.close()
                except DockerException:
                    pass
            return False, self._encode_result(
                f"Docker is unavailable: {exc}",
                {
                    "error_type": "docker_unavailable",
                    "duration_seconds": round(time.monotonic() - started, 3),
                },
            )

        container = None
        try:
            try:
                self._ensure_runner_image(client)
            except Exception as exc:
                return False, self._encode_result(
                    f"Docker runner image setup failed: {exc}",
                    {
                        "error_type": "docker_error",
                        "duration_seconds": round(time.monotonic() - started, 3),
                    },
                )
            command = [
                "sh",
                "-c",
                "python -m pytest -p no:cacheprovider --tb=short -q "
                "--junitxml=/tmp/testforge-junit.xml test_app.py; "
                "pytest_exit=$?; "
                "echo __TESTFORGE_PYTEST_EXIT_CODE__=$pytest_exit; "
                "if [ -f /tmp/testforge-junit.xml ]; then "
                "cat /tmp/testforge-junit.xml; fi; "
                "exit $pytest_exit",
            ]
            container = client.containers.run(
                self.image,
                command=command,
                working_dir="/workspace",
                volumes={workspace: {"bind": "/workspace", "mode": "ro"}},
                detach=True,
                auto_remove=False,
                network_disabled=True,
                read_only=True,
                user="65534:65534",
                mem_limit=self.memory_limit,
                nano_cpus=self.nano_cpus,
                pids_limit=self.pids_limit,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                tmpfs={"/tmp": "rw,noexec,nosuid,nodev,size=64m"},
                environment={
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                    "TMPDIR": "/tmp",
                },
                stdout=True,
                stderr=True,
            )

            deadline = time.monotonic() + self.timeout_seconds
            timed_out = False
            while time.monotonic() < deadline:
                container.reload()
                if container.status in {"exited", "dead"}:
                    break
                time.sleep(0.2)
            else:
                timed_out = True
                try:
                    container.stop(timeout=2)
                except DockerException:
                    try:
                        container.kill()
                    except DockerException:
                        pass

            raw_logs = container.logs(stdout=True, stderr=True)
            output = self._decode_logs(raw_logs)
            exit_code = (container.attrs.get("State") or {}).get("ExitCode")
            counts = self._parse_junit_counts(output)
            actual_duration = round(time.monotonic() - started, 3)

            if timed_out:
                metadata = {
                    **counts,
                    "exit_code": exit_code,
                    "timed_out": True,
                    "error_type": "execution_timeout",
                    "duration_seconds": actual_duration,
                }
                passed = False
                message = (
                    f"Docker test execution exceeded {self.timeout_seconds} seconds."
                )
            else:
                pytest_exit = self._parse_pytest_exit(output, exit_code)
                metadata = {
                    **counts,
                    "exit_code": pytest_exit,
                    "timed_out": False,
                    "error_type": None,
                    "duration_seconds": actual_duration,
                }
                metadata["error_type"], diagnosis = self._classify_pytest_result(
                    output=output,
                    route_code=Path(workspace, "main.py").read_text(encoding="utf-8"),
                    test_code=Path(workspace, "test_app.py").read_text(encoding="utf-8"),
                    pytest_exit=pytest_exit,
                    counts=counts,
                )
                if diagnosis is not None:
                    metadata["diagnosis"] = diagnosis
                    if metadata["error_type"] in {
                        "application_error",
                        "test_collection_error",
                        "invalid_generated_tests",
                    }:
                        # JUnit can count a collection/import error as a test error.
                        # Those are not collected endpoint assertions.
                        metadata.update(
                            collected=0,
                            passed=0,
                            failures=0,
                            skipped=0,
                            errors=max(counts["errors"], 1),
                        )
                passed = (
                    pytest_exit == 0
                    and counts["collected"] > 0
                    and counts["passed"] > 0
                    and counts["failures"] == 0
                    and counts["errors"] == 0
                    and counts["skipped"] < counts["collected"]
                )
                message = output

            return passed, self._encode_result(message, metadata)
        except DockerException as exc:
            return False, self._encode_result(
                f"Docker execution error: {exc}",
                {
                    "error_type": "docker_error",
                    "duration_seconds": round(time.monotonic() - started, 3),
                },
            )
        except Exception as exc:
            return False, self._encode_result(
                f"Sandbox execution error: {exc}",
                {
                    "error_type": "sandbox_error",
                    "duration_seconds": round(time.monotonic() - started, 3),
                },
            )
        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except DockerException:
                    pass
            try:
                client.close()
            except DockerException:
                pass

    @staticmethod
    def _classify_pytest_result(
        *, output: str, route_code: str, test_code: str,
        pytest_exit: int | None, counts: dict[str, int]
    ) -> tuple[str | None, dict[str, Any] | None]:
        """Classify execution failures from pytest output and the submitted source."""
        lower_output = output.lower()
        exception_type, exception_message = ExecutionSandbox._extract_exception(output)
        is_collection_error = bool(
            re.search(
                r"(?im)^\s*(?:E\s+)?ERROR\s+collecting\b|"
                r"\berror during collection\b|"
                r"ImportError while importing test module|"
                r"\bcollected 0 items?\s*\/\s*\d+ errors?",
                output,
            )
        )

        application_source_frame = re.search(
            r"(?im)(?:[A-Za-z]:)?[^\s\r\n]*[\\/]?main\.py:\d+:\s+in\s+<module>|"
            r"File\s+['\"][^'\"]*main\.py['\"],?\s+line\s+\d+",
            output,
        )

        # A FastAPIError from the submitted main.py while pytest is collecting
        # is conclusive initialization evidence. The exception name alone is
        # insufficient: generated test modules can also define invalid routes.
        is_fastapi_initialization_error = (
            pytest_exit == 2
            and is_collection_error
            and application_source_frame
            and (
                "fastapi.exceptions.fastapierror" in lower_output
                or "invalid args for response field" in lower_output
            )
        )
        if is_fastapi_initialization_error:
            model_name = ExecutionSandbox._find_invalid_request_model(route_code)
            if model_name:
                model_fields = ExecutionSandbox._get_annotated_model_fields(
                    route_code, model_name
                )
                cause = (
                    f"The {model_name} class is not a Pydantic BaseModel but is used "
                    "as a FastAPI request-body type."
                )
                message = (
                    f"FastAPI could not initialize the application because the "
                    f"{model_name} declaration is not a valid Pydantic request model. "
                    "Pytest could not collect the tests, so no endpoint assertions "
                    "were executed."
                )
                suggestion = (
                    "from pydantic import BaseModel\n\n"
                    f"class {model_name}(BaseModel):\n"
                ) + "\n".join(f"    {field}" for field in model_fields)
            else:
                cause = "FastAPI raised an initialization error while importing or registering a route."
                message = (
                    "FastAPI could not initialize the application while importing or "
                    "registering a route. Pytest could not collect the tests, so no "
                    "endpoint assertions were executed."
                )
                suggestion = None
            diagnosis = {
                "category": "application_error",
                "title": "Application Initialization Error",
                "message": message,
                "likely_cause": cause,
                "exception_type": exception_type or "FastAPIError",
                "exception_message": exception_message or "Invalid args for response field",
                "endpoint_assertions_ran": False,
            }
            if suggestion:
                diagnosis["suggestion"] = suggestion
            return "application_error", diagnosis

        if is_collection_error and application_source_frame:
            return "application_error", {
                "category": "application_error",
                "title": "Application Initialization Error",
                "message": (
                    "The application source failed while importing or registering "
                    "routes. Pytest could not collect the tests, so no endpoint "
                    "assertions were executed."
                ),
                "likely_cause": (
                    "An exception originated in main.py during application "
                    "initialization or route registration."
                ),
                "exception_type": exception_type,
                "exception_message": exception_message,
                "endpoint_assertions_ran": False,
                "suggestion": (
                    "Review the main.py traceback and correct the application "
                    "import or route-registration error before rerunning."
                ),
            }

        if is_collection_error:
            # Syntax and import mistakes in the generated test file are harness
            # failures. Other collection failures remain neutral and are never
            # sent to the model as evidence of an API defect.
            test_file_failure = "test_app.py" in lower_output and (
                "syntaxerror" in lower_output or "modulenotfounderror" in lower_output
            )
            if test_file_failure:
                return "invalid_generated_tests", {
                    "category": "invalid_generated_tests",
                    "title": "Test Collection Error",
                    "message": "Pytest could not import or parse the generated test file; no endpoint assertions ran.",
                    "exception_type": exception_type,
                    "exception_message": exception_message,
                    "endpoint_assertions_ran": False,
                }
            return "test_collection_error", {
                "category": "test_collection_error",
                "title": "Test Collection Error",
                "message": "Pytest encountered a collection/import error before endpoint assertions ran. This is not evidence of a failing API assertion.",
                "exception_type": exception_type,
                "exception_message": exception_message,
                "endpoint_assertions_ran": False,
            }

        if counts["collected"] == 0:
            if "syntaxerror" in lower_output and "test_app.py" in lower_output:
                return "invalid_generated_tests", {
                    "category": "invalid_generated_tests",
                    "title": "Generated Test Code Could Not Be Collected",
                    "message": "Pytest could not parse test_app.py, so no endpoint assertions ran.",
                    "endpoint_assertions_ran": False,
                }

            if (
                "syntaxerror" in lower_output and "main.py" in lower_output
            ) or ("error collecting" in lower_output and "main.py" in lower_output):
                return "application_error", {
                    "category": "application_error",
                    "title": "Application Could Not Initialize",
                    "message": (
                        f"The application source failed during import or route setup "
                        f"(pytest exit code {pytest_exit}); no endpoint assertions ran."
                    ),
                    "endpoint_assertions_ran": False,
                }

            if pytest_exit == 5:
                return "no_tests_collected", {
                    "category": "no_tests_collected",
                    "title": "No Tests Collected",
                    "message": "Pytest exited with code 5 without collecting any tests.",
                    "endpoint_assertions_ran": False,
                }

            if "error collecting" in lower_output or "importerror while importing" in lower_output:
                return "test_collection_error", {
                    "category": "test_collection_error",
                    "title": "Test Collection Error",
                    "message": (
                        "Pytest encountered an import or collection error before any "
                        "endpoint assertions ran. Inspect the traceback to determine "
                        "whether the generated test or application import failed."
                    ),
                    "endpoint_assertions_ran": False,
                }

            return "invalid_generated_tests", {
                "category": "invalid_generated_tests",
                "title": "Generated Tests Could Not Be Collected",
                "message": "Pytest collected no tests; this is not a passing run.",
                "endpoint_assertions_ran": False,
            }

        if counts["skipped"] == counts["collected"] and counts["collected"] > 0:
            return "all_tests_skipped", {
                "category": "all_tests_skipped",
                "title": "All Tests Were Skipped",
                "message": "Pytest collected tests but skipped every test, so API behavior was not verified.",
                "endpoint_assertions_ran": False,
            }

        if counts["errors"] > 0:
            is_setup_failure = bool(
                re.search(
                    r"(?im)ERROR\s+at\s+setup\s+of\b|"
                    r"fixture\s+['\"][^'\"]+['\"]\s+not\s+found|"
                    r"FixtureLookupError|ScopeMismatch",
                    output,
                )
            )
            if is_setup_failure:
                return "test_setup_error", {
                    "category": "test_setup_error",
                    "title": "Test Setup Error",
                    "message": "Pytest collected tests but failed during fixture or test setup. This does not by itself establish an API defect.",
                    "exception_type": exception_type,
                    "exception_message": exception_message,
                    "endpoint_assertions_ran": False,
                }
            return "inconclusive", {
                "category": "inconclusive",
                "title": "Test Run Inconclusive",
                "message": (
                    "Pytest collected tests but reported an execution error without "
                    "clear fixture-setup or assertion evidence. The run does not "
                    "confirm an API defect."
                ),
                "exception_type": exception_type,
                "exception_message": exception_message,
            }

        if counts["failures"] > 0:
            return "assertion_failure", {
                "category": "assertion_failure",
                "title": "API Assertion Failed",
                "message": "Executed API assertions failed. The failure needs classification before it can be called an application defect.",
                "endpoint_assertions_ran": True,
            }

        if pytest_exit != 0:
            return "pytest_error", {
                "category": "pytest_error",
                "title": "Pytest Execution Error",
                "message": "Pytest exited unsuccessfully; review the raw output for the execution cause.",
                "endpoint_assertions_ran": counts["collected"] > 0,
            }

        return None, None

    @staticmethod
    def _extract_exception(output: str) -> tuple[str | None, str | None]:
        pattern = re.compile(
            r"^\s*(?:E\s+)?((?:[A-Za-z_]\w*\.)*[A-Z]\w*(?:Error|Exception)):\s*(.+?)\s*$"
        )
        for line in output.splitlines():
            match = pattern.match(line)
            if match:
                message = match.group(2).split(" Hint:", 1)[0].strip()
                return match.group(1).rsplit(".", 1)[-1], message[:300]
        return None, None

    @staticmethod
    def _find_invalid_request_model(route_code: str) -> str | None:
        """Find a non-Pydantic class used in a decorated FastAPI route parameter."""
        try:
            tree = ast.parse(route_code)
        except SyntaxError:
            return None

        non_model_classes: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = {
                base.id if isinstance(base, ast.Name) else getattr(base, "attr", None)
                for base in node.bases
            }
            if "BaseModel" not in bases:
                non_model_classes.add(node.name)

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            is_route = any(
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr in {"get", "post", "put", "patch", "delete"}
                for decorator in node.decorator_list
            )
            if not is_route:
                continue
            for argument in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
                if argument.annotation is None:
                    continue
                for child in ast.walk(argument.annotation):
                    if isinstance(child, ast.Name) and child.id in non_model_classes:
                        return child.id
        return None

    @staticmethod
    def _get_annotated_model_fields(route_code: str, model_name: str) -> list[str]:
        try:
            tree = ast.parse(route_code)
        except SyntaxError:
            return ["# Keep the model's existing annotated fields here"]
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == model_name:
                fields = [
                    ast.unparse(statement)
                    for statement in node.body
                    if isinstance(statement, ast.AnnAssign)
                ]
                return fields or ["# Keep the model's existing annotated fields here"]
        return ["# Keep the model's existing annotated fields here"]

    def _ensure_runner_image(self, client: docker.DockerClient) -> None:
        try:
            client.images.get(self.image)
            return
        except ImageNotFound:
            pass

        # Only trusted build instructions enter this build context. User source
        # and generated tests are mounted later, into a network-disabled container.
        with _IMAGE_BUILD_LOCK:
            try:
                client.images.get(self.image)
                return
            except ImageNotFound:
                with tempfile.TemporaryDirectory(prefix="testforge-image-") as context:
                    dockerfile = Path(context) / "Dockerfile"
                    dockerfile.write_text(
                        "FROM python:3.11-slim\n"
                        "RUN pip install --no-cache-dir fastapi pytest httpx2 pydantic "
                        "email-validator\n",
                        encoding="utf-8",
                    )
                    # This runner is built only from Docker Hub's public base
                    # image; do not invoke a configured credential helper.
                    # Docker SDK otherwise reloads the user's credential-helper
                    # config when the auth map is empty. The empty public-registry
                    # entry avoids sending or invoking any stored credentials.
                    client.api._auth_configs = docker.auth.AuthConfig(
                        {"auths": {"https://index.docker.io/v1/": {}}}
                    )
                    client.images.build(
                        path=context,
                        dockerfile="Dockerfile",
                        tag=self.image,
                        rm=True,
                        forcerm=True,
                    )

    @staticmethod
    def _decode_logs(value: bytes | str) -> str:
        if isinstance(value, bytes):
            return value[-MAX_LOG_BYTES:].decode("utf-8", errors="replace")
        return value[-MAX_LOG_BYTES:]

    @staticmethod
    def _parse_junit_counts(output: str) -> dict[str, int]:
        tests = failures = errors = skipped = 0
        xml_start = output.rfind("<testsuites")
        xml_end = output.find("</testsuites>", xml_start)
        if xml_start >= 0 and xml_end >= 0:
            xml_text = output[xml_start : xml_end + len("</testsuites>")]
            try:
                root = ET.fromstring(xml_text)
                suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
                tests = sum(int(suite.attrib.get("tests", "0")) for suite in suites)
                failures = sum(
                    int(suite.attrib.get("failures", "0")) for suite in suites
                )
                errors = sum(int(suite.attrib.get("errors", "0")) for suite in suites)
                skipped = sum(
                    int(suite.attrib.get("skipped", "0")) for suite in suites
                )
            except (ET.ParseError, ValueError):
                pass

        if not tests:
            summary = re.search(r"(?:=+\s*)?(.+?)\s+in\s+[\d.]+s\s*=+", output)
            if summary:
                text = summary.group(1)
                for amount, label in re.findall(
                    r"(\d+)\s+(passed|failed|error|errors|skipped)", text
                ):
                    count = int(amount)
                    if label == "passed":
                        tests += count
                    elif label == "failed":
                        tests += count
                        failures += count
                    elif label in {"error", "errors"}:
                        tests += count
                        errors += count
                    else:
                        tests += count
                        skipped += count

        return {
            "collected": tests,
            "passed": max(0, tests - failures - errors - skipped),
            "failures": failures,
            "errors": errors,
            "skipped": skipped,
        }

    @staticmethod
    def _parse_pytest_exit(output: str, container_exit: int | None) -> int | None:
        match = re.search(r"__TESTFORGE_PYTEST_EXIT_CODE__=(\d+)", output)
        return int(match.group(1)) if match else container_exit

    @staticmethod
    def _encode_result(output: str, metadata: dict[str, Any]) -> str:
        return (
            f"{output.rstrip()}\n{RESULT_MARKER}"
            f"{json.dumps(metadata, separators=(',', ':'), sort_keys=True)}"
        )
