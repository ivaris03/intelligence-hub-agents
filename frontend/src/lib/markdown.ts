import DOMPurify from 'dompurify'
import { marked } from 'marked'

marked.setOptions({ breaks: true, gfm: true })

export function renderMarkdown(content: string): string {
  const sanitized = DOMPurify.sanitize(marked.parse(content) as string, {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ['script', 'style', 'iframe', 'object', 'embed', 'form'],
    FORBID_ATTR: ['style', 'onerror', 'onload'],
  })
  const document = new DOMParser().parseFromString(sanitized, 'text/html')
  for (const link of document.querySelectorAll('a')) {
    link.setAttribute('target', '_blank')
    link.setAttribute('rel', 'noopener noreferrer')
  }
  return document.body.innerHTML
}
