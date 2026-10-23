import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { closeSync, existsSync, lstatSync, mkdirSync, openSync, readFileSync, realpathSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, isAbsolute, join, relative, resolve, sep } from 'node:path';
import { createInterface } from 'node:readline/promises';
import { fileURLToPath } from 'node:url';
import { findExecutable, requireVenv } from './installer-utils.mjs';

export const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
export const helpText = `Configure df mcp to read one explicitly selected local folder.\n\n  --root <folder>       Source folder (read only; relative paths use the current directory)\n  --state-dir <folder>  Override the application state base; profiles are created below it\n  --yes                Confirm without a prompt; requires explicit --root\n  --help               Show this help\n\nWindows uses a folder picker when no --root is provided; other systems ask for a path.\nNo source directory is scanned and no MCP process is started by this installer.`;

export function parseArguments(argv, { allowSkip = false } = {}) {
  const options = {};
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--root' || arg === '--state-dir') {
      if (options[arg] !== undefined || !argv[i + 1] || argv[i + 1].startsWith('--')) throw new Error(`Supply exactly one value for ${arg}.`);
      options[arg] = argv[++i];
    } else if (arg === '--yes' || arg === '--help' || (arg === '--skip-config' && allowSkip)) {
      if (options[arg]) throw new Error(`Duplicate option: ${arg}`);
      options[arg] = true;
    } else throw new Error(`Unknown argument: ${arg}`);
  }
  if (options['--yes'] && !options['--root']) throw new Error('--yes requires an explicit --root.');
  if (options['--skip-config'] && (options['--root'] || options['--state-dir'] || options['--yes'])) throw new Error('--skip-config cannot be combined with configuration options.');
  return options;
}

export function defaultStateBase({ platform = process.platform, env = process.env, home = homedir() } = {}) {
  if (platform === 'win32') {
    if (!env.LOCALAPPDATA || !isAbsolute(env.LOCALAPPDATA)) throw new Error('LOCALAPPDATA is unavailable. Supply --state-dir explicitly.');
    return join(env.LOCALAPPDATA, 'df-mcp');
  }
  if (platform === 'darwin') return join(home, 'Library', 'Application Support', 'df-mcp');
  if (env.XDG_STATE_HOME && !isAbsolute(env.XDG_STATE_HOME)) throw new Error('XDG_STATE_HOME must be absolute.');
  return join(env.XDG_STATE_HOME || join(home, '.local', 'state'), 'df-mcp');
}

function stripOuterQuotes(value) {
  const trimmed = value.trim();
  return trimmed.length > 1 && ((trimmed.startsWith('"') && trimmed.endsWith('"')) || (trimmed.startsWith("'") && trimmed.endsWith("'"))) ? trimmed.slice(1, -1) : trimmed;
}

export function canonicalFuturePath(path) {
  const missing = [];
  let current = resolve(path);
  while (!existsSync(current)) {
    const parent = dirname(current);
    if (parent === current) throw new Error('Unable to resolve the storage location.');
    missing.unshift(current.slice(parent.length + (parent.endsWith(sep) ? 0 : 1)));
    current = parent;
  }
  return resolve(realpathSync.native(current), ...missing);
}

function contained(parent, child, platform) {
  const normalizedParent = platform === 'win32' ? parent.toLowerCase() : parent;
  const normalizedChild = platform === 'win32' ? child.toLowerCase() : child;
  const difference = relative(normalizedParent, normalizedChild);
  return difference === '' || (!difference.startsWith(`..${sep}`) && difference !== '..' && !isAbsolute(difference));
}

function rejectStorageLinks(path) {
  let current = resolve(path);
  while (true) {
    try {
      if (lstatSync(current).isSymbolicLink()) throw new Error('The state location must not use symbolic links or junctions. Choose another --state-dir.');
    } catch (error) { if (error.code !== 'ENOENT') throw error; }
    const parent = dirname(current);
    if (parent === current) return;
    current = parent;
  }
}

export function makePlan(rootInput, stateInput, { repo = repositoryRoot, platform = process.platform, env = process.env, home = homedir() } = {}) {
  const sourceInput = stripOuterQuotes(rootInput);
  if (!sourceInput || sourceInput.includes('\0')) throw new Error('A non-empty source folder is required.');
  const sourcePath = resolve(sourceInput);
  const sourceStat = lstatSync(sourcePath);
  if (!sourceStat.isDirectory() || sourceStat.isSymbolicLink()) throw new Error('Select an ordinary local directory, not a link or a file.');
  const root = realpathSync.native(sourcePath);
  const installRoot = realpathSync.native(repo);
  const baseInput = resolve(stateInput ? stripOuterQuotes(stateInput) : defaultStateBase({ platform, env, home }));
  rejectStorageLinks(baseInput);
  const base = canonicalFuturePath(baseInput);
  const key = createHash('sha256').update(platform === 'win32' ? root.toLowerCase() : root).digest('hex').slice(0, 16);
  const profile = join(base, 'profiles', key);
  const state = join(profile, 'state');
  if (contained(root, installRoot, platform) || contained(installRoot, root, platform)) throw new Error('The source folder and df mcp installation must not overlap. Select a dedicated document folder outside the installation.');
  if (contained(root, base, platform) || contained(base, root, platform)) throw new Error('Source and state storage must be separate, non-overlapping folders.');
  if (contained(installRoot, base, platform) || contained(base, installRoot, platform)) throw new Error('State storage and the df mcp installation must not overlap.');
  rejectStorageLinks(profile);
  return { root, sourcePath, base, profile, state, configPath: join(profile, 'config.json'), repo: installRoot, platform };
}

export function preflightRoot(root, { repo = repositoryRoot, platform = process.platform, env = process.env } = {}) {
  const python = requireVenv(repo, platform);
  const result = spawnSync(python, ['-m', 'team_drive.fs_access', '--validate-root', root], {
    cwd: repo, env: { ...env, PYTHONPATH: join(repo, 'python'), PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8', PYTHONDONTWRITEBYTECODE: '1' }, encoding: 'utf8', timeout: 15000, windowsHide: true,
  });
  let response;
  try { response = JSON.parse(result.stdout || '{}'); } catch { /* Report a bounded diagnostic without subprocess traces. */ }
  if (result.error || result.status !== 0 || response?.ok !== true) throw new Error(`Source folder security validation failed (${response?.error?.code || response?.code || 'VALIDATION_FAILED'}). Choose a normal local folder and check that dependencies are installed.`);
}

export function windowsFolderPicker({ env = process.env, runner = spawnSync } = {}) {
  const executable = findExecutable('powershell', { platform: 'win32', env });
  if (!executable) return { unavailable: true };
  const script = `[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false); Add-Type -AssemblyName System.Windows.Forms; $dialog = New-Object System.Windows.Forms.FolderBrowserDialog; $dialog.Description = 'Select the folder df mcp may read (read only)'; $dialog.ShowNewFolderButton = $false; if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { @{ selected = $dialog.SelectedPath } | ConvertTo-Json -Compress } else { @{ cancelled = $true } | ConvertTo-Json -Compress }; $dialog.Dispose()`;
  const result = runner(executable, ['-NoProfile', '-STA', '-Command', script], { env, encoding: 'utf8', windowsHide: true });
  if (result.error || result.status !== 0) return { unavailable: true };
  try { return JSON.parse(result.stdout.trim().replace(/^\uFEFF/, '')); } catch { return { unavailable: true }; }
}

function sameConfig(existing, config) { return JSON.stringify(existing) === JSON.stringify(config); }

export function writeConfiguration(plan) {
  const config = { provider: 'local', root: plan.root, state_dir: plan.state, poll_seconds: 30 };
  rejectStorageLinks(plan.profile);
  if (existsSync(plan.configPath)) {
    if (lstatSync(plan.configPath).isSymbolicLink()) throw new Error('Refusing to replace a linked configuration file.');
    let existing;
    try { existing = JSON.parse(readFileSync(plan.configPath, 'utf8')); } catch { throw new Error('An existing configuration cannot be read. It was not changed.'); }
    if (!sameConfig(existing, config)) throw new Error('This profile already has a different configuration. Nothing was overwritten; inspect it or choose another --state-dir.');
    return { config, reused: true };
  }
  mkdirSync(plan.profile, { recursive: true, mode: 0o700 });
  rejectStorageLinks(plan.profile);
  const handle = openSync(plan.configPath, 'wx', 0o600);
  try { writeFileSync(handle, `${JSON.stringify(config, null, 2)}\n`, 'utf8'); } finally { closeSync(handle); }
  return { config, reused: false };
}

export function shellQuote(value, platform = process.platform) {
  return platform === 'win32' ? `'${value.replaceAll("'", "''")}'` : `'${value.replaceAll("'", "'\\''")}'`;
}

export async function runConfigure(argv = [], runtime = {}) {
  const options = parseArguments(argv);
  const platform = runtime.platform || process.platform;
  const output = runtime.output || process.stdout;
  const input = runtime.input || process.stdin;
  const log = (message) => output.write(`${message}\n`);
  if (options['--help']) { log(helpText); return { help: true }; }
  const interactive = runtime.interactive ?? Boolean(input.isTTY && output.isTTY);
  if (!interactive && !options['--root']) throw new Error('Non-interactive configuration requires --root <folder> --yes. No default source folder is selected.');
  if (!interactive && !options['--yes']) throw new Error('Non-interactive confirmation requires --yes together with an explicit --root.');
  let reader;
  const ask = runtime.ask || (async (question) => {
    reader ||= createInterface({ input, output });
    return reader.question(question);
  });
  try {
    let source = options['--root'];
    if (!source && platform === 'win32') {
      const picked = await (runtime.pickFolder || windowsFolderPicker)({ env: runtime.env || process.env });
      if (picked.cancelled) { log('Cancelled. No configuration or index was created.'); return { cancelled: true }; }
      source = picked.selected;
      if (!source) log('Folder picker unavailable. Paste the folder path instead.');
    }
    if (!source) source = await ask('Source folder (read only; blank cancels): ');
    if (!source.trim()) { log('Cancelled. No configuration or index was created.'); return { cancelled: true }; }
    const plan = makePlan(source, options['--state-dir'], { repo: runtime.repo || repositoryRoot, platform, env: runtime.env || process.env, home: runtime.home || homedir() });
    const validate = runtime.validateRoot || preflightRoot;
    await validate(plan.sourcePath, { repo: plan.repo, platform, env: runtime.env || process.env });
    log(`Source folder (READ ONLY): ${plan.root}\nPrivate state/index directory: ${plan.state}\nConfiguration: ${plan.configPath}\nSource files will not be created, edited, renamed, or deleted. No source ACLs are changed.`);
    if (!options['--yes']) {
      const answer = await ask('Save this configuration? [y/N]: ');
      if (!/^(y|yes)$/i.test(answer.trim())) { log('Cancelled. No configuration or index was created.'); return { cancelled: true }; }
    }
    // Revalidate after the user confirms, before creating any storage.
    const fresh = makePlan(source, options['--state-dir'], { repo: runtime.repo || repositoryRoot, platform, env: runtime.env || process.env, home: runtime.home || homedir() });
    if (fresh.root !== plan.root || fresh.configPath !== plan.configPath) throw new Error('A selected path changed during configuration. Nothing was written; try again.');
    await validate(plan.sourcePath, { repo: plan.repo, platform, env: runtime.env || process.env });
    const result = writeConfiguration(plan);
    log(`${result.reused ? 'Existing identical configuration reused.' : 'Configuration saved.'} Indexing starts only when the MCP client starts the server.\nRegister in Codex (PowerShell on Windows):\ncodex mcp add df_mcp -- node ${shellQuote(join(plan.repo, 'dist', 'index.js'), platform)} --config ${shellQuote(plan.configPath, platform)}\nInstall the skill separately with: npm run install:skill\nDo not start two MCP connections with the same state directory; remove or disable an older connection first.`);
    return { ...result, plan };
  } finally { reader?.close(); }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runConfigure(process.argv.slice(2)).catch((error) => { console.error(error.message); process.exitCode = 1; });
}
