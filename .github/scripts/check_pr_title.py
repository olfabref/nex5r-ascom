"""Checks that the PR title (env PR_TITLE) follows Conventional Commits.

With squash merge, the PR title becomes the commit message on main. The title is read from the
environment, never interpolated into the shell, so a crafted title cannot run code in CI.
"""
import os
import re
import sys

TYPES = ('feat', 'fix', 'docs', 'style', 'refactor', 'perf', 'test', 'build', 'ci', 'chore', 'revert')
PATTERN = re.compile(r'^(%s)(\([a-z0-9][a-z0-9._/-]*\))?!?: \S.*$' % '|'.join(TYPES))


def main() -> int:
    title = os.environ.get('PR_TITLE', '')
    if PATTERN.match(title):
        print('PR title OK')
        return 0
    print('The PR title must follow Conventional Commits: "<type>(<optional scope>)!: <description>", '
          'with type one of: ' + ', '.join(TYPES) + '. Example: "feat(alpaca-server): Focuser device".',
          file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
