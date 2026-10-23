import { cpSync, existsSync, mkdirSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const target = join(process.env.CODEX_HOME || join(homedir(), '.codex'), 'skills', 'team-drive-read');
if (existsSync(target)) { console.error('Skill already exists; inspect and update it explicitly. Nothing was overwritten.'); process.exit(1); }
mkdirSync(dirname(target), { recursive: true });
cpSync(join(root, 'skills/team-drive-read'), target, { recursive: true, errorOnExist: true });
console.log('Installed team-drive-read. Configure the MCP server separately, then start a new session.');
