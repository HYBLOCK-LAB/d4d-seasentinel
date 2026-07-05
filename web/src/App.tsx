import { Suspense, lazy } from 'react'
import styles from './App.module.css'
import { MapView } from './map/MapView'
import { AppStateProvider, useAppState } from './state/AppState'
import { TopBar } from './shell/TopBar'

const LeftRail = lazy(() => import('./shell/LeftRail'))
const RightDrawer = lazy(() => import('./shell/RightDrawer').then((m) => ({ default: m.RightDrawer })))
const Timebar = lazy(() => import('./shell/Timebar').then((m) => ({ default: m.Timebar })))
const DataLayers = lazy(() => import('./layers/DataLayers'))

function Shell() {
  const { rightPanel } = useAppState()
  return (
    <div className={styles.app}>
      <TopBar />
      <div className={styles.main}>
        <Suspense fallback={null}>
          <LeftRail />
        </Suspense>
        <div className={styles.center}>
          <MapView>
            <Suspense fallback={null}>
              <DataLayers />
            </Suspense>
          </MapView>
          <Suspense fallback={null}>
            <Timebar />
          </Suspense>
        </div>
        {rightPanel && (
          <Suspense fallback={null}>
            <RightDrawer />
          </Suspense>
        )}
      </div>
    </div>
  )
}

function KeyedShell() {
  const { settings } = useAppState()
  return <Shell key={settings.dataset} />
}

export default function App() {
  return (
    <AppStateProvider>
      <KeyedShell />
    </AppStateProvider>
  )
}
