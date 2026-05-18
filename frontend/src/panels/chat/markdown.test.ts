// @vitest-environment jsdom

import { describe, expect, it } from 'vitest';

import { renderMarkdown } from './markdown';

describe('renderMarkdown', () => {
  it('removes script tags and event handlers from report-derived content', () => {
    const rendered = renderMarkdown('<img src=x onerror=alert(1)><script>alert(2)</script>');

    expect(rendered).not.toContain('<script');
    expect(rendered).not.toContain('onerror');
    expect(rendered).toContain('<img');
  });

  it('removes svg payloads from markdown html', () => {
    const rendered = renderMarkdown('"><svg onload=alert(1)><circle /></svg>');

    expect(rendered).not.toContain('<svg');
    expect(rendered).not.toContain('onload');
  });

  it('blocks javascript urls while keeping normal markdown links', () => {
    const rendered = renderMarkdown('[bad](javascript:alert(1)) [good](https://example.com)');

    expect(rendered).not.toContain('javascript:');
    expect(rendered).toContain('href="https://example.com"');
  });
});
