import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import test from 'node:test';
import { inspectConfiguration, parseDoctorArguments } from '../scripts/doctor.mjs';
import { parseCallArguments } from '../scripts/call-tool.mjs';

function fixture(t) {
  const base = realpathSync(mkdtempSync(join(tmpdir(), 'df-doctor-')));
  const repo = join(base, 'install'), source = join(base, 'source'), state = join(base, 'state');
  mkdirSync(join(repo, 'dist'), { recursive: true }); mkdirSync(source);
  writeFileSync(join(repo, 'package.json'), JSON.stringify({ version: '0.3.0' }));
  writeFileSync(join(repo, 'dist/index.js'), "const server = { name: 'df-mcp', version: '0.3.0' };\n");
  const config = join(base, 'config.json');
  writeFileSync(config, JSON.stringify({ root: './source', state_dir: './state', service: { idle_seconds: 60, max_clients: 64 } }));
  writeFileSync(join(source, 'evidence.txt'), 'SIMULATED do not alter');
  t.after(() => rmSync(base, { recursive: true, force: true }));
  return { base, repo, source, state, config, env: {} };
}

test('offline doctor shows explicit source and build without creating state or changing files', t => {
  const f = fixture(t), original = readFileSync(f.config);
  const result = inspectConfiguration(f.config, { repo: f.repo, env: {}, home: f.base });
  assert.equal(result.ok, true);
  assert.equal(result.source_path, f.source);
  assert.equal(result.package_version, '0.3.0');
  assert.equal(result.built_version, '0.3.0');
  assert.equal(result.connection_checked, false);
  assert.equal(result.source_scanned, false);
  assert.equal(existsSync(f.state), false);
  assert.deepEqual(readFileSync(f.config), original);
  assert.equal(readFileSync(join(f.source, 'evidence.txt'), 'utf8'), 'SIMULATED do not alter');
});

test('doctor reports stale build and unsafe Codex storage without creating it', t => {
  const f = fixture(t);
  writeFileSync(join(f.repo, 'dist/index.js'), "const server = { name: 'df-mcp', version: '0.2.0' };\n");
  const state = join(f.base, '.codex', 'state');
  writeFileSync(f.config, JSON.stringify({ root: f.source, state_dir: state }));
  const result = inspectConfiguration(f.config, { repo: f.repo, env: {}, home: f.base });
  assert.equal(result.ok, false);
  assert.equal(result.checks.find(item => item.name === 'built_entrypoint').ok, false);
  assert.equal(result.checks.find(item => item.name === 'state_location').ok, false);
  assert.equal(existsSync(state), false);
});

test('doctor rejects overlap and malformed service options while retaining diagnostics', t => {
  const f = fixture(t);
  writeFileSync(f.config, JSON.stringify({ root: f.source, state_dir: join(f.source, 'cache'), service: { max_clients: 0 } }));
  const result = inspectConfiguration(f.config, { repo: f.repo, env: {}, home: f.base });
  assert.equal(result.ok, false);
  assert.equal(result.checks.find(item => item.name === 'state_location').ok, false);
  assert.equal(result.checks.find(item => item.name === 'runtime_options').ok, false);
  assert.equal(existsSync(join(f.source, 'cache')), false);
});

test('diagnostic CLI requires a source selection before starting a service', t => {
  const f = fixture(t);
  assert.throws(() => parseCallArguments([]), /No implicit source/);
  assert.throws(() => parseCallArguments(['--demo', '--config', f.config]), /exactly one/);
  assert.throws(() => parseCallArguments(['team_drive_read', '[]', '--config', f.config]), /JSON object/);
  assert.throws(() => parseDoctorArguments([]), /--config/);
  assert.equal(parseCallArguments(['team_drive_status', '--config', f.config]).config, f.config);
  assert.equal(parseCallArguments(['tools', '--demo']).demo, true);
  const child = spawnSync(process.execPath, [resolve('scripts/call-tool.mjs')], { encoding: 'utf8', env: { ...process.env, DF_MCP_PYTHON: join(f.base, 'must-not-start') } });
  assert.equal(child.status, 1);
  assert.match(child.stderr, /No implicit source/);
  assert.equal(existsSync(f.state), false);
});
