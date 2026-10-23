import { randomUUID } from 'node:crypto';
import { cpSync, existsSync, lstatSync, mkdirSync, readdirSync, renameSync, rmSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');

function ordinaryDirectory(path) {
  const stat = lstatSync(path);
  if (!stat.isDirectory() || stat.isSymbolicLink()) throw new Error('Skill locations must be ordinary directories, not links.');
}

function assertNoLinks(path) {
  ordinaryDirectory(path);
  for (const entry of readdirSync(path, { withFileTypes: true })) {
    const child = join(path, entry.name);
    if (entry.isSymbolicLink()) throw new Error('The skill package contains a link and cannot be installed.');
    if (entry.isDirectory()) assertNoLinks(child);
    else if (!entry.isFile()) throw new Error('The skill package contains an unsupported file type.');
  }
}

export function installSkill(argv = [], { repo = repositoryRoot, codexHome = process.env.CODEX_HOME || join(homedir(), '.codex'), log = console.log } = {}) {
  if (argv.includes('--help')) { log('Install df-mcp: npm run install:skill\nExplicit upgrade/migration: npm run install:skill -- --replace\nExisting skills are backed up outside the skills directory before replacement.'); return { help: true }; }
  if (argv.some((arg) => arg !== '--replace') || argv.length > 1) throw new Error('Only --replace or --help is supported.');
  const replace = argv.includes('--replace');
  const source = join(repo, 'skills', 'df-mcp');
  const home = resolve(codexHome);
  const skills = join(home, 'skills');
  const target = join(skills, 'df-mcp');
  const legacy = join(skills, 'team-drive-read');
  assertNoLinks(source);
  for (const directory of [home, skills, join(home, 'skill-backups')]) if (existsSync(directory)) ordinaryDirectory(directory);
  const previous = [target, legacy].filter(existsSync);
  for (const directory of previous) ordinaryDirectory(directory);
  if (previous.length && !replace) throw new Error('An existing df-mcp or team-drive-read skill was found. Nothing was changed. Review it, then use --replace to back it up and explicitly upgrade/migrate.');
  // Prepare the entire package outside the discoverable skills directory before changing old skills.
  const transaction = join(home, 'skill-backups', `${new Date().toISOString().replaceAll(':', '-')}-${randomUUID().slice(0, 8)}`);
  const staged = join(transaction, 'incoming');
  mkdirSync(transaction, { recursive: true, mode: 0o700 });
  const moved = [];
  try {
    cpSync(source, staged, { recursive: true, errorOnExist: true, force: false });
    mkdirSync(skills, { recursive: true, mode: 0o700 });
    for (const old of previous) {
      const backup = join(transaction, old === legacy ? 'team-drive-read' : 'df-mcp');
      renameSync(old, backup);
      moved.push({ old, backup });
    }
    if (existsSync(target)) throw new Error('The destination changed during installation; refusing to overwrite it.');
    renameSync(staged, target);
  } catch (error) {
    for (const item of moved.reverse()) if (!existsSync(item.old)) renameSync(item.backup, item.old);
    rmSync(staged, { recursive: true, force: true });
    throw error;
  }
  if (!moved.length) rmSync(transaction, { recursive: true });
  log(`Installed df mcp (skill identifier: df-mcp). Start a new session to use $df-mcp.\nConfigure the MCP source separately with npm run configure.${moved.length ? `\nPrevious skill content was preserved at: ${transaction}` : ''}`);
  return { target, backups: moved.map((item) => item.backup) };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { installSkill(process.argv.slice(2)); } catch (error) { console.error(error.message); process.exitCode = 1; }
}
