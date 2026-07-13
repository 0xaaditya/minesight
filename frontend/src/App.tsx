import { Route, BrowserRouter, Routes } from 'react-router-dom'
import { VehiclesPage } from './pages/VehiclesPage'
import { MapPage } from './pages/MapPage'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<VehiclesPage />} />
        <Route path="/map" element={<MapPage />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
