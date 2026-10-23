import { Client } from '@modelcontextprotocol/client';
import { StdioClientTransport } from '@modelcontextprotocol/client/stdio';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
let [name = 'team_drive_status', raw = '{}', config = join(root, 'examples/config.sample.json')] = process.argv.slice(2);
if (name === '--list') name = 'tools';
if (name === '--help') {
  console.log('Usage: node scripts/call-tool.mjs [tools|TOOL_NAME] [JSON_ARGUMENTS] [CONFIG_PATH]\nThis diagnostic client waits up to 60 seconds for startup indexing. Use a persistent MCP client for large libraries.');
  process.exit(0);
}
const client = new Client({ name: 'team-drive-cli', version: '0.1.0' });
async function waitForJob(jobId) {
  const until = Date.now() + 60_000;
  while (Date.now() < until) {
    const wire = await client.callTool({ name: 'team_drive_job_status', arguments: jobId ? { job_id: jobId } : {} });
    const result = wire.structuredContent;
    if (!result?.ok) return result;
    if (!['queued', 'running'].includes(result.job.status)) return result;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error('Indexing is still running. Use a persistent MCP client for this library.');
}
try {
  await client.connect(new StdioClientTransport({ command: process.execPath, args: [join(root, 'dist/index.js'), '--config', resolve(config)], stderr: 'pipe' }));
  if (name === 'tools') console.log(JSON.stringify(await client.listTools(), null, 2));
  else {
    if (!['team_drive_cancel', 'team_drive_job_status'].includes(name)) {
      const startup = await waitForJob();
      if (startup && !startup.ok) { console.log(JSON.stringify(startup, null, 2)); process.exitCode = 1; }
    }
    if (!process.exitCode) {
      const result = await client.callTool({ name, arguments: JSON.parse(raw) });
      const body = result.structuredContent || result;
      if (name === 'team_drive_refresh' && body.ok) body.completion = await waitForJob(body.job_id);
      console.log(JSON.stringify(body, null, 2)); if (result.isError) process.exitCode = 1;
    }
  }
} catch (error) {
  console.error('Tool call failed: ' + (error instanceof Error ? error.message : 'unknown error'));
  process.exitCode = 1;
} finally { await client.close(); }
