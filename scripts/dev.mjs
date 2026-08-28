import { spawn, spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { StringDecoder } from 'node:string_decoder';
import { fileURLToPath } from 'node:url';

const repoRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const workerDir = join(repoRoot, 'backend', 'python-worker');
const apiDir = join(repoRoot, 'backend', 'node-api');
const webDir = join(repoRoot, 'frontend');
const isWindows = process.platform === 'win32';
const pythonExe = join(
  workerDir,
  '.venv',
  isWindows ? 'Scripts' : 'bin',
  isWindows ? 'python.exe' : 'python',
);
const npmExe = isWindows ? 'npm.cmd' : 'npm';

const prerequisites = [
  [join(repoRoot, 'backend', '.env'), 'Thiếu backend/.env. Hãy sao chép từ backend/.env.example và điền cấu hình.'],
  [pythonExe, 'Thiếu Python trong backend/python-worker/.venv. Hãy tạo virtual environment và cài requirements.txt.'],
  [join(apiDir, 'node_modules'), 'Thiếu dependency Backend API. Hãy chạy npm install trong backend/node-api.'],
  [join(webDir, 'node_modules'), 'Thiếu dependency Frontend. Hãy chạy npm install trong frontend.'],
];

for (const [path, message] of prerequisites) {
  if (!existsSync(path)) {
    process.stderr.write(`[dev] ${message}\n`);
    process.exit(1);
  }
}

const definitions = [
  { name: 'worker', command: pythonExe, args: ['main.py'], cwd: workerDir },
  { name: 'api', command: npmExe, args: ['run', 'dev'], cwd: apiDir },
  { name: 'web', command: npmExe, args: ['run', 'dev', '--', '--strictPort'], cwd: webDir },
];

const children = [];
let shuttingDown = false;

function pipeWithPrefix(stream, target, prefix) {
  const decoder = new StringDecoder('utf8');
  let pending = '';
  stream.on('data', (chunk) => {
    pending += decoder.write(chunk);
    const lines = pending.split(/\r?\n/);
    pending = lines.pop() ?? '';
    for (const line of lines) {
      target.write(`[${prefix}] ${line}\n`);
    }
  });
  stream.on('end', () => {
    pending += decoder.end();
    if (pending) target.write(`[${prefix}] ${pending}\n`);
  });
}

function terminateTree(child) {
  if (!child.pid || child.exitCode !== null) return;
  if (isWindows) {
    spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], {
      stdio: 'ignore',
      windowsHide: true,
    });
    return;
  }
  try {
    process.kill(-child.pid, 'SIGTERM');
  } catch {
    try {
      child.kill('SIGTERM');
    } catch {
      // The process already exited.
    }
  }
}

function forceTerminateTree(child) {
  if (isWindows || !child.pid || child.exitCode !== null) return;
  try {
    process.kill(-child.pid, 'SIGKILL');
  } catch {
    // The process group already exited.
  }
}

function shutdown(exitCode = 0) {
  if (shuttingDown) return;
  shuttingDown = true;
  process.stdout.write('\n[dev] Đang dừng các dịch vụ...\n');
  for (const child of children) terminateTree(child);
  process.exitCode = exitCode;
  const forceDeadline = setTimeout(() => {
    for (const child of children) forceTerminateTree(child);
  }, 1000);
  forceDeadline.unref();
  const deadline = setTimeout(() => process.exit(exitCode), 1500);
  deadline.unref();
}

for (const definition of definitions) {
  const child = spawn(definition.command, definition.args, {
    cwd: definition.cwd,
    env: process.env,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
    detached: !isWindows,
  });
  children.push(child);
  pipeWithPrefix(child.stdout, process.stdout, definition.name);
  pipeWithPrefix(child.stderr, process.stderr, definition.name);
  child.on('error', (error) => {
    process.stderr.write(`[${definition.name}] Không thể khởi động: ${error.message}\n`);
    shutdown(1);
  });
  child.on('exit', (code, signal) => {
    if (shuttingDown) return;
    const detail = signal ? `signal ${signal}` : `mã ${code ?? 1}`;
    process.stderr.write(`[${definition.name}] Đã dừng ngoài dự kiến (${detail}).\n`);
    shutdown(code && code > 0 ? code : 1);
  });
}

process.on('SIGINT', () => shutdown(0));
process.on('SIGTERM', () => shutdown(0));
process.on('SIGHUP', () => shutdown(0));
process.stdout.write('[dev] SentriAI đang chạy. Nhấn Ctrl+C để dừng tất cả dịch vụ.\n');
