import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import Home from './pages/Home'
import Settings from './pages/Settings'
import Create from './pages/Create/index'
import Chat from './pages/Chat'
import ExDetail from './pages/ExDetail'

export default function App() {
  return (
    <Routes>
      {/* Chat takes full screen, no sidebar */}
      <Route path="/chat/:slug" element={<Chat />} />

      {/* All other pages use the sidebar layout */}
      <Route path="/*" element={
        <Layout>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/create" element={<Create />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/ex/:slug" element={<ExDetail />} />
          </Routes>
        </Layout>
      } />
    </Routes>
  )
}
