// Offline validation shared by configure/doctor. Keep bounds and keys aligned
// with team_drive.service_config.settings and Engine; this never starts a worker.
const limitKeys = new Set(['max_file_bytes', 'max_uncompressed_bytes', 'max_segments', 'max_segment_chars', 'max_columns', 'max_pdf_pages', 'parse_timeout_seconds']);
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);

export function validateRuntimeOptions(config) {
  if (!object(config) || (config.provider !== undefined && config.provider !== 'local')) throw new Error('Only a local source configuration is supported.');
  if (config.poll_seconds !== undefined && (typeof config.poll_seconds !== 'number' || !Number.isFinite(config.poll_seconds) || config.poll_seconds < 1 || config.poll_seconds > 86400)) throw new Error('poll_seconds must be a finite number between 1 and 86400.');
  if (config.limits !== undefined) {
    if (!object(config.limits) || Object.entries(config.limits).some(([key, value]) => !limitKeys.has(key) || !Number.isSafeInteger(value) || value < 1)) throw new Error('limits must use known keys and positive safe integers.');
  }
  if (config.aliases !== undefined && (!object(config.aliases) || Object.values(config.aliases).some(values => !Array.isArray(values) || values.some(value => typeof value !== 'string')))) throw new Error('aliases must map strings to lists of strings.');
  if (config.service !== undefined) {
    if (!object(config.service)) throw new Error('service must be an object.');
    for (const [name, value] of Object.entries(config.service)) {
      const maximum = name === 'idle_seconds' ? 3600 : name === 'max_clients' ? 256 : undefined;
      if (!maximum || typeof value !== 'number' || !Number.isFinite(value) || (name === 'max_clients' && !Number.isInteger(value)) || value < 1 || value > maximum) throw new Error(`Unsupported service setting: ${name}.`);
    }
  }
  return config;
}
