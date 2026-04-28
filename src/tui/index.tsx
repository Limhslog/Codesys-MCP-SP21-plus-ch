import React from 'react';
import { render } from 'ink';
import { Text } from 'ink';

const argv = process.argv.slice(2);

if (argv[0] === '--version' || argv[0] === '-v') {
  process.stdout.write('phobiCS-tui v0.1.0\n');
  process.exit(0);
}

render(<Text>phobiCS-tui — coming soon</Text>);
