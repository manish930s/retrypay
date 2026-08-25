import { describe, expect, it } from 'vitest';

import { resolveApiBase } from '../api';

describe('resolveApiBase', () => {
  it('falls back to local proxy default when explicit value is empty', () => {
    expect(resolveApiBase('')).toBe('/api/v1');
    expect(resolveApiBase('   ')).toBe('/api/v1');
  });

  it('removes trailing slashes from configured values', () => {
    expect(resolveApiBase('/api/v1/')).toBe('/api/v1');
    expect(resolveApiBase('https://api.example.com/api/v1///')).toBe(
      'https://api.example.com/api/v1'
    );
  });
});
