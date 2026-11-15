import { MotionConfig } from 'motion/react'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { Guide } from './components/guide.tsx'

// One extra page, so no router: the Worker serves index.html for every path.
const isGuide = location.pathname.replace(/\/+$/, '') === '/guide'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {/* Motion follows the visitor's reduced-motion setting: positions change at once, opacity still fades. */}
    <MotionConfig reducedMotion="user">{isGuide ? <Guide /> : <App />}</MotionConfig>
  </StrictMode>,
)
