type TabId = 'browse' | 'editor' | 'chat' | 'today' | 'pending'

export function MobileTabBar(props: { active: TabId; onSelect: (id: TabId) => void }) {
  const tabs: { id: TabId; label: string; icon: string }[] = [
    { id: 'browse', label: 'Browse', icon: '☰' },
    { id: 'editor', label: 'Editor', icon: '✎' },
    { id: 'chat', label: 'Chat', icon: '✉' },
    { id: 'today', label: 'Today', icon: '✓' },
    { id: 'pending', label: 'Pending', icon: '▦' },
  ]

  return (
    <nav className="mobileTabBar" aria-label="Ochre navigation">
      {tabs.map((t) => (
        <button
          key={t.id}
          type="button"
          className={props.active === t.id ? 'mobileTabButton active' : 'mobileTabButton'}
          onClick={() => props.onSelect(t.id)}
        >
          <span className="mobileTabIcon" aria-hidden="true">
            {t.icon}
          </span>
          <span className="mobileTabLabel">{t.label}</span>
        </button>
      ))}
    </nav>
  )
}

