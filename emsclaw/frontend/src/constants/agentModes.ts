export interface AgentModeMeta {
  value: string
  label: string
  icon: string // emoji for quick rendering
  description: string
}

export const AGENT_MODES: AgentModeMeta[] = [
  { value: 'business', label: 'Business', icon: '💼', description: 'Lead + domain expert sub-agents' },
]

export const DEFAULT_MODE = 'business'

export function getModeMeta(mode: string | undefined | null): AgentModeMeta {
  return AGENT_MODES.find(m => m.value === mode) ?? AGENT_MODES[0]
}
