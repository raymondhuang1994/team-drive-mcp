import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const isWin = process.platform === 'win32';
const python = process.env.TEAM_DRIVE_PYTHON || (isWin ? 'python' : 'python3');
function run(cmd, args) { const result = spawnSync(cmd, args, { cwd: root, stdio: 'inherit' }); if (result.error || result.status !== 0) { console.error('Setup failed. Check Node >=22 and Python >=3.9.'); process.exit(1); } }
if (!existsSync(join(root, '.venv'))) run(python, ['-m', 'venv', '.venv']);
run(join(root, '.venv', isWin ? 'Scripts/python.exe' : 'bin/python'), ['-m', 'pip', 'install', '-r', 'requirements.txt']);
run(process.execPath, [join(root, 'node_modules/typescript/bin/tsc')]);
console.log('Local setup complete. Run npm test, then configure the MCP client using examples/mcp.json.');
