import { describe, expect, it } from 'vitest'

import { renderMarkdown } from './markdown'

describe('renderMarkdown', () => {
  it('sanitizes active HTML and secures external links', () => {
    const html = renderMarkdown('[来源](https://example.com)<script>alert(1)</script>')
    expect(html).not.toContain('<script')
    expect(html).toContain('target="_blank"')
    expect(html).toContain('rel="noopener noreferrer"')
  })
})
