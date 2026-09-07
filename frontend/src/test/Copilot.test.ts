import { describe, expect, it } from 'vitest'
import { collapseToolEvents, isReconnectNotice, waitingLabel } from '../components/Copilot'

describe('Copilot event presentation', () => {
  it('replaces a running tool event with its completed details', () => {
    const events = collapseToolEvents([
      { sequence: 1, kind: 'agent_event', timestamp: 1, payload: { kind: 'tool', call_id: 'call-1', status: 'running', input_detail: '{"name":"api"}' } },
      { sequence: 2, kind: 'agent_event', timestamp: 2, payload: { kind: 'tool', call_id: 'call-1', status: 'completed', output_detail: '{"id":"42"}', duration_seconds: 1.25 } },
    ])
    expect(events).toHaveLength(1)
    expect(events[0].payload.status).toBe('completed')
    expect(events[0].payload.output_detail).toContain('42')
  })

  it('changes the waiting copy as the operation takes longer', () => {
    expect(waitingLabel(1)).not.toBe(waitingLabel(20))
    expect(waitingLabel(20)).not.toBe(waitingLabel(70))
  })

  it('hides transport reconnect notices from current and persisted chats', () => {
    expect(isReconnectNotice({
      sequence: 1,
      kind: 'agent_event',
      timestamp: 1,
      payload: { kind: 'warning', title: 'Поток событий переподключается' },
    })).toBe(true)
    expect(isReconnectNotice({
      sequence: 2,
      kind: 'agent_event',
      timestamp: 1,
      payload: { kind: 'warning', title: 'Важное предупреждение' },
    })).toBe(false)
  })
})
