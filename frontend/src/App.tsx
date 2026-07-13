import { Route, BrowserRouter, Routes } from 'react-router-dom'
import { Shell } from './layout/Shell'
import { HomePage } from './pages/HomePage'
import { MapPage } from './pages/MapPage'
import { VehiclesPage } from './pages/VehiclesPage'
import { VehicleDetailPage } from './pages/VehicleDetailPage'
import { LangProvider } from './i18n/strings'

function App() {
  return (
    <LangProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Shell />}>
            <Route index element={<HomePage />} />
            <Route path="map" element={<MapPage />} />
            <Route path="vehicles" element={<VehiclesPage />} />
            <Route path="vehicles/:id" element={<VehicleDetailPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </LangProvider>
  )
}

export default App
