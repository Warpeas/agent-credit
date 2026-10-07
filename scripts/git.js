const { execFileSync } = require('child_process');
const path = require('path');
// Derive the repo from this script's own location, so no absolute path is baked in.
const workTree = path.resolve(__dirname, '..');
const gitDir = path.join(workTree, '.git');
function run(...args) {
  const out = execFileSync('git', ['--git-dir', gitDir, '--work-tree', workTree, ...args], { encoding: 'utf-8', shell: false });
  if (out) process.stdout.write(out);
}
const cmd = process.argv[2];
if (cmd === 'status') run('status', '--short');
else if (cmd === 'add') run('add', '-A');
else if (cmd === 'commit') run('commit', '-m', process.argv.slice(3).join(' '));
else if (cmd === 'push') run('push', 'origin', 'HEAD');
else console.log('usage: node _git.js status|add|commit|push');
