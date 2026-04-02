import { NavLink } from 'react-router-dom'

export default function Layout({ children }) {
  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="sidebar-logo">
          <div className="brand-main">忘不掉的她</div>
          <div className="brand-sub">Memory Companion</div>
        </div>
        <ul className="sidebar-nav">
          <li>
            <NavLink to="/" end className={({ isActive }) => isActive ? 'active' : ''}>
              <span>💝</span> 全部
            </NavLink>
          </li>
          <li>
            <NavLink to="/create" className={({ isActive }) => isActive ? 'active' : ''}>
              <span>✨</span> 新建
            </NavLink>
          </li>
          <li>
            <NavLink to="/settings" className={({ isActive }) => isActive ? 'active' : ''}>
              <span>⚙️</span> 设置
            </NavLink>
          </li>
        </ul>
      </aside>
      <main className="main-content">
        <div className="mobile-brand">
          <div className="brand-main">忘不掉的她</div>
          <div className="brand-sub">你的情感记忆档案</div>
        </div>
        {children}
      </main>
    </div>
  )
}
