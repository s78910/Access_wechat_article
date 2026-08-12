export type LogMessageSegment =
  | {
      type: 'text'
      text: string
    }
  | {
      type: 'url'
      text: string
      fullText: string
    }

const HTTPS_URL_PATTERN = /(https:\/\/\S+)/u

export function formatLogMessageSegments(message: string): LogMessageSegment[] {
  const text = String(message ?? '')
  const match = text.match(HTTPS_URL_PATTERN)
  if (match?.index === undefined || !match[1]) {
    return [{ type: 'text', text }]
  }

  return [
    { type: 'text', text: text.slice(0, match.index) },
    { type: 'url', text: match[1], fullText: match[1] },
  ]
}
