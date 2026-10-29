const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

let pythonCmd;
const venvWin = path.join(__dirname, '..', 'venv', 'Scripts', 'python.exe');
const venvUnix = path.join(__dirname, '..', 'venv', 'bin', 'python');

if (fs.existsSync(venvWin)) {
  pythonCmd = venvWin;
} else if (fs.existsSync(venvUnix)) {
  pythonCmd = venvUnix;
} else if (process.env.VIRTUAL_ENV) {
  pythonCmd = process.platform === 'win32'
    ? path.join(process.env.VIRTUAL_ENV, 'Scripts', 'python.exe')
    : path.join(process.env.VIRTUAL_ENV, 'bin', 'python');
} else {
  pythonCmd = process.platform === 'win32' ? 'py' : 'python3';
}

console.log(`Starting server using ${pythonCmd}...`);
const result = spawnSync(pythonCmd, ['manage.py', 'runserver', '0.0.0.0:8000'], {
  stdio: 'inherit',
  cwd: path.join(__dirname, '..'),
});

if (result.error) {
  console.error('Failed to run server:', result.error);
  process.exit(1);
}

process.exit(result.status ?? 0);

