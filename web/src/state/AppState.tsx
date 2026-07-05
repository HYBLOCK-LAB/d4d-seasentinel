import { createContext, useContext, useEffect, useReducer, type Dispatch, type ReactNode } from 'react'
import { api, setDataset } from '../api/client'
import type { Meta, Region, TimeWindow } from '../api/types'
import { DEFAULT_REGION_ID, FALLBACK_REGIONS } from '../constants/regions'

export type RightPanel = 'ontology' | 'copilot' | 'osint' | 'settings' | null

export interface Settings {
  theme: 'dark' | 'light'
  model: string
  autoRefresh: boolean
  dataset: string
  datasetLabel: string
}

export interface AppState {
  regions: Region[]
  regionId: string
  window: TimeWindow
  fullRange: TimeWindow
  layersEnabled: Record<string, boolean>
  selectedThreatId: string | null
  rightPanel: RightPanel
  ontologyFocus: { table: string; srcId?: string } | null
  focusTarget: { lon: number; lat: number } | null
  meta: Meta | null
  playing: boolean
  settings: Settings
}

export type Action =
  | { type: 'meta'; meta: Meta }
  | { type: 'region'; regionId: string }
  | { type: 'window'; window: TimeWindow }
  | { type: 'layer'; id: string; on: boolean }
  | { type: 'selectThreat'; id: string | null }
  | { type: 'rightPanel'; panel: RightPanel }
  | { type: 'ontologyFocus'; focus: { table: string; srcId?: string } | null }
  | { type: 'focus'; target: { lon: number; lat: number } | null }
  | { type: 'playing'; on: boolean }
  | { type: 'settings'; patch: Partial<Settings> }

export const DEFAULT_LAYERS: Record<string, boolean> = {
  ais_points: true,
  tracks: true,
  alerts_geo: true,
  events: true,
  zones: true,
  cables: true,
  ports: true,
}

export const DEFAULT_SETTINGS: Settings = {
  theme: 'dark',
  model: '',
  autoRefresh: true,
  dataset: '',
  datasetLabel: '',
}

const SETTINGS_STORAGE_KEY = 'seasentinel.settings'

function loadSettings(): Settings {
  try {
    const raw = localStorage.getItem(SETTINGS_STORAGE_KEY)
    if (!raw) return DEFAULT_SETTINGS
    const parsed = JSON.parse(raw) as Partial<Settings>
    return { ...DEFAULT_SETTINGS, ...parsed }
  } catch {
    return DEFAULT_SETTINGS
  }
}

function hoursAgo(end: string, h: number): string {
  return new Date(new Date(end).getTime() - h * 3600_000).toISOString()
}

const initialEnd = new Date().toISOString()

export const initialState: AppState = {
  regions: FALLBACK_REGIONS,
  regionId: DEFAULT_REGION_ID,
  window: { start: hoursAgo(initialEnd, 72), end: initialEnd },
  fullRange: { start: hoursAgo(initialEnd, 24 * 30), end: initialEnd },
  layersEnabled: DEFAULT_LAYERS,
  selectedThreatId: null,
  rightPanel: null,
  ontologyFocus: null,
  focusTarget: null,
  meta: null,
  playing: false,
  settings: loadSettings(),
}

setDataset(initialState.settings.dataset)

function reducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case 'meta': {
      const w = action.meta.window
      return {
        ...state,
        meta: action.meta,
        regions: action.meta.regions.length ? action.meta.regions : state.regions,
        window: w,
        fullRange: w,
      }
    }
    case 'region':
      return { ...state, regionId: action.regionId, selectedThreatId: null }
    case 'window':
      return { ...state, window: action.window }
    case 'layer':
      return { ...state, layersEnabled: { ...state.layersEnabled, [action.id]: action.on } }
    case 'selectThreat':
      return { ...state, selectedThreatId: action.id }
    case 'rightPanel':
      return { ...state, rightPanel: action.panel }
    case 'ontologyFocus':
      return {
        ...state,
        ontologyFocus: action.focus,
        rightPanel: action.focus ? 'ontology' : state.rightPanel,
      }
    case 'focus':
      return { ...state, focusTarget: action.target }
    case 'playing':
      return { ...state, playing: action.on }
    case 'settings':
      return { ...state, settings: { ...state.settings, ...action.patch } }
  }
}

const StateCtx = createContext<AppState>(initialState)
const DispatchCtx = createContext<Dispatch<Action>>(() => {})

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState)
  setDataset(state.settings.dataset)
  useEffect(() => {
    api.meta().then(
      (meta) => dispatch({ type: 'meta', meta }),
      () => {},
    )
  }, [state.settings.dataset])
  useEffect(() => {
    localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(state.settings))
    document.documentElement.dataset.theme = state.settings.theme
  }, [state.settings])
  return (
    <StateCtx.Provider value={state}>
      <DispatchCtx.Provider value={dispatch}>{children}</DispatchCtx.Provider>
    </StateCtx.Provider>
  )
}

export function useAppState(): AppState {
  return useContext(StateCtx)
}

export function useAppDispatch(): Dispatch<Action> {
  return useContext(DispatchCtx)
}

export function useRegion(): Region {
  const s = useAppState()
  return s.regions.find((r) => r.id === s.regionId) ?? (FALLBACK_REGIONS[0] as Region)
}

export function useSettings(): Settings {
  return useAppState().settings
}
