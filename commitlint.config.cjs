module.exports = {
  extends: ['@commitlint/config-conventional'],
  rules: {
    'type-enum': [
      2,
      'always',
      ['feat', 'fix', 'docs', 'chore', 'refactor', 'test', 'build', 'ci', 'perf', 'revert'],
    ],
    'scope-enum': [
      2,
      'always',
      ['ingest', 'sim', 'tax', 'vault', 'mcp', 'web', 'dbt', 'infra', 'docs', 'deps', 'ci', 'release', 'repo'],
    ],
    'scope-empty': [0],
    'subject-case': [2, 'never', ['upper-case']],
    'header-max-length': [2, 'always', 100],
  },
};
