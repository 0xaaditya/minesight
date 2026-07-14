import { useEffect, useState, type ComponentType } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import {
  Bell,
  BellRing,
  CalendarClock,
  ChevronRight,
  ClipboardList,
  Fuel,
  GitFork,
  Hexagon,
  History,
  Layers,
  LayoutDashboard,
  Map as MapIcon,
  PanelLeft,
  Route as RouteIcon,
  ScrollText,
  Search,
  ShieldAlert,
  Truck,
  User,
  UserCog,
  Users,
} from 'lucide-react'
import { useLang, useT, type Lang } from '../i18n/strings'
import { todayIST, useEvents, useVehicles } from '../api/client'
import { VehicleDrawer } from '../components/VehicleDrawer'

export type ReplayRequest = { vehicleId: string; date: string }

type NavItem = {
  to: string | null
  labelKey: 'home' | 'liveMap' | 'vehiclesDevices' | null
  label: string | null
  icon: ComponentType<{ size?: number }>
}

type NavGroup = { label: string; items: NavItem[] }

const NAV_GROUPS: NavGroup[] = [
  {
    label: 'DASHBOARD',
    items: [
      { to: '/', labelKey: 'home', label: null, icon: LayoutDashboard },
      { to: null, labelKey: null, label: 'Fleet Overview', icon: GitFork },
      { to: null, labelKey: null, label: 'Trip Dashboard', icon: RouteIcon },
      { to: null, labelKey: null, label: 'Fuel & Theft', icon: Fuel },
      { to: null, labelKey: null, label: 'Incidents', icon: ShieldAlert },
    ],
  },
  {
    label: 'TRACKING',
    items: [
      { to: '/map', labelKey: 'liveMap', label: null, icon: MapIcon },
      { to: null, labelKey: null, label: 'Route Replay', icon: History },
      { to: null, labelKey: null, label: 'All Equipment', icon: Layers },
    ],
  },
  {
    label: 'OPERATIONS',
    items: [
      { to: null, labelKey: null, label: 'Assignments', icon: ClipboardList },
      { to: null, labelKey: null, label: 'Shifts', icon: CalendarClock },
      { to: null, labelKey: null, label: 'Drivers', icon: Users },
      { to: null, labelKey: null, label: 'Zones', icon: Hexagon },
    ],
  },
  {
    label: 'ADMIN',
    items: [
      { to: '/vehicles', labelKey: 'vehiclesDevices', label: null, icon: Truck },
      { to: null, labelKey: null, label: 'Users & Roles', icon: UserCog },
      { to: null, labelKey: null, label: 'Alerts Settings', icon: BellRing },
      { to: null, labelKey: null, label: 'Audit Log', icon: ScrollText },
    ],
  },
]

const BREADCRUMB: Record<string, 'home' | 'liveMap' | 'vehiclesDevices'> = {
  '/': 'home',
  '/map': 'liveMap',
  '/vehicles': 'vehiclesDevices',
}

const LANGS: { code: Lang; label: string }[] = [
  { code: 'en', label: 'EN' },
  { code: 'hi', label: 'हिं' },
  { code: 'mr', label: 'मरा' },
]

// Below this the sidebar switches from an inline column (240/64px) to an off-canvas
// overlay — keep in sync with the 720px breakpoint in index.css's responsive section.
const MOBILE_BREAKPOINT_PX = 720

function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState(
    () => window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT_PX}px)`).matches,
  )
  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT_PX}px)`)
    const onChange = (e: MediaQueryListEvent) => setIsMobile(e.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])
  return isMobile
}

function useISTClock() {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(id)
  }, [])
  return {
    time: now.toLocaleTimeString('en-GB', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit' }),
    date: now.toLocaleDateString('en-GB', {
      timeZone: 'Asia/Kolkata',
      day: '2-digit',
      month: 'short',
      year: 'numeric',
    }),
  }
}

export function Shell() {
  const [sidebarOpen, setSidebarOpen] = useState(true)
  // Mobile nav is separate state from desktop collapse: the overlay defaults closed
  // and every navigation closes it, while desktop expanded/collapsed persists.
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const isMobile = useIsMobile()
  const [selectedVehicleId, setSelectedVehicleId] = useState<string | null>(null)
  const [replay, setReplay] = useState<ReplayRequest | null>(null)
  const { lang, setLang } = useLang()
  const T = useT()
  const clock = useISTClock()
  const location = useLocation()
  const navigate = useNavigate()
  const { data: vehicles } = useVehicles()
  // Same query as HomePage's event card — React Query dedupes by key, no extra requests.
  const { data: events } = useEvents()
  const unackedCount = (events ?? []).filter((e) => !e.acknowledged_at).length

  // Prefix match covers nested routes like /vehicles/:id (exact-key lookup would
  // silently fall back to "home" there).
  const breadcrumbKey =
    BREADCRUMB[location.pathname] ?? (location.pathname.startsWith('/vehicles') ? 'vehiclesDevices' : 'home')
  const selectedVehicle = vehicles?.find((v) => v.id === selectedVehicleId) ?? null

  // Replay only makes sense on the map — jump there and close the drawer so the
  // replay panel (which lives inside MapPage/LiveMap) is immediately visible.
  const startReplay = (vehicleId: string) => {
    setReplay({ vehicleId, date: todayIST() })
    setSelectedVehicleId(null)
    navigate('/map')
  }

  // In the mobile overlay the rail always shows full labels — the desktop 64px
  // icon-rail collapse is meaningless off-canvas.
  const labelsVisible = isMobile || sidebarOpen
  const sidebarClass = isMobile
    ? `ls-sidebar${mobileNavOpen ? ' ls-sidebar-mobile-open' : ''}`
    : `ls-sidebar${sidebarOpen ? '' : ' ls-sidebar-collapsed'}`

  return (
    <div className="ls-shell">
      {isMobile && mobileNavOpen && (
        <div className="ls-sidebar-backdrop" onClick={() => setMobileNavOpen(false)} />
      )}
      <aside className={sidebarClass}>
        <div className="ls-sidebar-brand">
          <div className="ls-logo">L</div>
          {labelsVisible && (
            <div className="ls-brand-text">
              <div className="ls-brand-name">Lodestar</div>
              <div className="ls-brand-sub">Fleet & Anti-theft</div>
            </div>
          )}
        </div>
        <nav className="ls-nav">
          {NAV_GROUPS.map((group) => (
            <div className="ls-nav-group" key={group.label}>
              {labelsVisible && <div className="ls-nav-group-label">{group.label}</div>}
              {group.items.map((item) => {
                const Icon = item.icon
                const label = item.labelKey ? T(item.labelKey) : item.label!
                if (!item.to) {
                  return (
                    <div className="ls-nav-item ls-nav-item-disabled" key={label} title={label}>
                      <Icon size={18} />
                      {labelsVisible && <span>{label}</span>}
                    </div>
                  )
                }
                return (
                  <NavLink
                    to={item.to}
                    end={item.to === '/'}
                    key={label}
                    title={label}
                    className={({ isActive }) => `ls-nav-item${isActive ? ' ls-nav-item-active' : ''}`}
                    onClick={() => setMobileNavOpen(false)}
                  >
                    <Icon size={18} />
                    {labelsVisible && <span>{label}</span>}
                  </NavLink>
                )
              })}
            </div>
          ))}
        </nav>
        <div className="ls-sidebar-footer">
          <span className="ls-status-dot" />
          {labelsVisible && <span>{T('poweredBy')} · v0.9.2</span>}
        </div>
      </aside>

      <div className="ls-main">
        <header className="ls-header">
          <button
            className="ls-icon-btn"
            onClick={() => (isMobile ? setMobileNavOpen((v) => !v) : setSidebarOpen((v) => !v))}
            aria-label="Toggle sidebar"
          >
            <PanelLeft size={17} />
          </button>
          <div className="ls-breadcrumb">
            <span>Lodestar</span>
            <ChevronRight size={14} />
            <span className="ls-breadcrumb-current">{T(breadcrumbKey)}</span>
          </div>
          <div className="ls-search">
            <Search size={16} />
            <input placeholder={T('searchPlaceholder')} />
          </div>
          <div className="ls-clock">
            <span className="ls-clock-time">{clock.time}</span>
            <span className="ls-clock-date">{clock.date} IST</span>
          </div>
          <div className="ls-lang-switch">
            {LANGS.map((l) => (
              <button
                key={l.code}
                className={lang === l.code ? 'ls-lang-active' : ''}
                onClick={() => setLang(l.code)}
              >
                {l.label}
              </button>
            ))}
          </div>
          <button
            className="ls-icon-btn ls-bell-btn"
            aria-label={unackedCount > 0 ? `${unackedCount} ${T('unackedEvents')}` : 'Notifications'}
          >
            <Bell size={17} />
            {unackedCount > 0 && <span className="ls-bell-badge">{unackedCount > 9 ? '9+' : unackedCount}</span>}
          </button>
          <div className="ls-avatar">
            <User size={16} />
          </div>
        </header>

        <div className="ls-content">
          <Outlet context={{ openVehicle: setSelectedVehicleId, replay, setReplay }} />
        </div>
      </div>

      {selectedVehicle && (
        <VehicleDrawer
          vehicle={selectedVehicle}
          onClose={() => setSelectedVehicleId(null)}
          onReplay={startReplay}
        />
      )}
    </div>
  )
}
