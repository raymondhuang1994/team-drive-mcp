import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import test from 'node:test';
import { inspectConfiguration, parseDoctorArguments } from '../scripts/doctor.mjs';
import { parseCallArguments } from '../scripts/call-tool.mjs';
import { validateRuntimeOptions } from '../scripts/config-validation.mjs';
import { venvPython } from '../scripts/installer-utils.mjs';

function fixture(t) {
  const base = realpathSync(mkdtempSync(join(tmpdir(), 'df-doctor-')));
  const repo = join(base, 'install'), source = join(base, 'source'), state = join(base, 'state');
  mkdirSync(join(repo, 'dist'), { recursive: true }); mkdirSync(source);
  writeFileSync(join(repo, 'package.json'), JSON.stringify({ version: '0.3.0' }));
  writeFileSync(join(repo, 'dist/index.js'), "const server = { name: 'df-mcp', version: '0.3.0' };\n");
  const pythonDirectory = join(repo, '.venv', process.platform === 'win32' ? 'Scripts' : 'bin'); mkdirSync(pythonDirectory, { recursive: true });
  const python = join(pythonDirectory, process.platform === 'win32' ? 'python.exe' : 'python'); writeFileSync(python, 'not-executed-by-offline-doctor'); chmodSync(python, 0o700);
  const config = join(base, 'config.json');
  writeFileSync(config, JSON.stringify({ root: './source', state_dir: './state', service: { idle_seconds: 60, max_clients: 64 } }));
  writeFileSync(join(source, 'evidence.txt'), 'SIMULATED do not alter');
  t.after(() => rmSync(base, { recursive: true, force: true }));
  return { base, repo, source, state, config, python, env: {} };
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

test('doctor rejects every runtime setting the installer would refuse to reuse', t => {
  const f = fixture(t), original = JSON.parse(readFileSync(f.config, 'utf8'));
  const bad = [{ poll_seconds: 86401 }, { poll_seconds: true }, { aliases: [] }, { aliases: { word: ['valid', 1] } }, { limits: null }, { limits: { max_pdf_pages: 1.5 } }, { limits: { unsupported: 1 } }, { service: JSON.parse('{"constructor":1}') }];
  for (const change of bad) {
    writeFileSync(f.config, JSON.stringify({ ...original, ...change }));
    const result = inspectConfiguration(f.config, { repo: f.repo, env: {}, home: f.base });
    assert.equal(result.ok, false, JSON.stringify(change));
    assert.equal(result.checks.find(item => item.name === 'runtime_options').ok, false);
    assert.equal(existsSync(f.state), false);
  }
});

test('doctor fails missing interpreters and resolves an explicitly selected executable on PATH', t => {
  const f = fixture(t);
  rmSync(f.python);
  const missing = inspectConfiguration(f.config, { repo: f.repo, env: {}, home: f.base });
  assert.equal(missing.ok, false);
  assert.equal(missing.checks.find(item => item.name === 'python_executable').ok, false);
  const name = process.platform === 'win32' ? 'python.exe' : 'python';
  const executable = join(f.base, name); writeFileSync(executable, 'not-executed'); chmodSync(executable, 0o700);
  const selected = inspectConfiguration(f.config, { repo: f.repo, env: { DF_MCP_PYTHON: 'python', PATH: f.base }, home: f.base });
  assert.equal(selected.ok, true);
  assert.equal(selected.python, executable);
  if (process.platform !== 'win32') {
    chmodSync(executable, 0o600);
    assert.equal(inspectConfiguration(f.config, { repo: f.repo, env: { DF_MCP_PYTHON: executable }, home: f.base }).ok, false);
  }
  assert.equal(existsSync(f.state), false);
});

test('offline runtime-option checks agree with real Python service configuration', t => {
  const f = fixture(t), repo = resolve('.');
  const cases = [{}, { poll_seconds: 1 }, { poll_seconds: 86400 }, { poll_seconds: 86401 }, { poll_seconds: true }, { aliases: {} }, { aliases: { word: ['synonym'] } }, { aliases: { word: 'bad' } }, { limits: { max_segments: 1 } }, { limits: { max_segments: 1.5 } }, { limits: { unknown: 1 } }, { service: { idle_seconds: 1.5, max_clients: 256 } }, { service: { idle_seconds: 3601 } }, { service: { max_clients: 1.5 } }, { service: JSON.parse('{"__proto__":1}') }];
  const expected = cases.map(config => { try { validateRuntimeOptions(config); return true; } catch { return false; } });
  const script = 'import json,pathlib,sys\nfrom team_drive.service_config import settings\nfrom team_drive.errors import DriveError\np=pathlib.Path(sys.argv[1]); results=[]\nfor options in json.loads(sys.argv[2]):\n p.write_text(json.dumps(dict(root=sys.argv[3],state_dir=sys.argv[4],**options)),encoding="utf-8")\n try: settings(str(p)); results.append(True)\n except DriveError: results.append(False)\nprint(json.dumps(results))';
  const child = spawnSync(venvPython(repo), ['-c', script, f.config, JSON.stringify(cases), f.source, f.state], { encoding: 'utf8', env: { ...process.env, PYTHONPATH: join(repo, 'python'), PYTHONDONTWRITEBYTECODE: '1', PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' }, timeout: 15000 });
  assert.equal(child.status, 0, child.stderr);
  assert.deepEqual(JSON.parse(child.stdout), expected);
  assert.equal(existsSync(f.state), false);
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
