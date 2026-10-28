import test from 'node:test';
import assert from 'node:assert/strict';
import { analyzeFastApiRoutes, synthesizePytestSuite, generateExecutionLogs } from './testForgeEngine.js';

test('analyzeFastApiRoutes identifies route decorators and methods', () => {
  const sampleCode = `
from fastapi import FastAPI
app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/users/")
def create_user(user: dict):
    return user
  `;

  const analysis = analyzeFastApiRoutes(sampleCode);
  assert.equal(analysis.routes.length, 2);
  assert.equal(analysis.routes[0].method, 'GET');
  assert.equal(analysis.routes[0].path, '/health');
  assert.equal(analysis.routes[1].method, 'POST');
  assert.equal(analysis.routes[1].path, '/users/');
  assert.equal(analysis.hasDefect, false);
});

test('analyzeFastApiRoutes detects ZeroDivisionError defects', () => {
  const buggyCode = `
@app.post("/api/v1/checkout")
def checkout(payload: dict):
    # Bug: division by zero when discount_factor is 1.0
    tax_rate = 100 / (1.0 - payload["discount_factor"])
    return {"tax": tax_rate}
  `;

  const analysis = analyzeFastApiRoutes(buggyCode);
  assert.equal(analysis.hasDefect, true);
  assert.ok(analysis.defectInfo);
  assert.match(analysis.defectInfo.type, /ZeroDivisionError/);
});

test('synthesizePytestSuite generates pytest test file with test cases', () => {
  const analysis = {
    routes: [
      { method: 'GET', path: '/items' },
      { method: 'POST', path: '/items' }
    ],
    hasDefect: false
  };

  const suite = synthesizePytestSuite('# sample code', analysis);
  assert.match(suite, /import pytest/);
  assert.match(suite, /from fastapi.testclient import TestClient/);
  assert.match(suite, /def test_get_items_success/);
  assert.match(suite, /def test_post_items_success/);
});

test('generateExecutionLogs outputs informative agent log steps', () => {
  const analysis = {
    routes: [{ method: 'GET', path: '/status' }],
    totalLines: 15,
    hasDefect: false
  };

  const logs = generateExecutionLogs(analysis, false);
  assert.ok(Array.isArray(logs));
  assert.ok(logs.length >= 10);
  assert.ok(logs.some(l => l.includes('TestForge Autonomous QA Agent')));
  assert.ok(logs.some(l => l.includes('SUCCESS')));
});
