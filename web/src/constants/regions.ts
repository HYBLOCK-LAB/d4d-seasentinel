import type { Region } from '../api/types'

export const FALLBACK_REGIONS: Region[] = [
  { id: 'west_sea', name: 'Korean West Sea (Yellow Sea)', bbox: [124.0, 34.5, 126.6, 38.6], theatre: 'ROK west coast / NLL', priority: 'primary' },
  { id: 'south_china_sea', name: 'South China Sea', bbox: [109.0, 9.5, 118.0, 19.6], theatre: 'APAC gray-zone reefs', priority: 'secondary' },
  { id: 'baltic', name: 'Baltic Sea', bbox: [9.0, 53.0, 30.0, 60.0], theatre: 'undersea-cable corridor', priority: 'secondary' },
]

export const DEFAULT_REGION_ID = 'west_sea'
