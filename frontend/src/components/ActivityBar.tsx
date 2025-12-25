type Item = 'explorer' | 'sessions' | 'chat' | 'kanban' | 'settings'

export function ActivityBar(props: {
  active: Item
  onSelect: (item: Item) => void
}) {
  const items: { id: Item; label: string; icon: string }[] = [
    { id: 'explorer', label: 'Explorer', icon: '☰' },
    { id: 'sessions', label: 'Sessions', icon: '⎘' },
    { id: 'chat', label: 'Chat', icon: '✉' },
    { id: 'kanban', label: 'Kanban', icon: '▦' },
    { id: 'settings', label: 'Settings', icon: '⚙' },
  ]

  return (
    <div className="activityBar">
      {items.map((it) => (
        <button
          key={it.id}
          className={props.active === it.id ? 'activityItem active' : 'activityItem'}
          title={it.label}
          onClick={() => props.onSelect(it.id)}
        >
          <span className="activityIcon">{it.icon}</span>
        </button>
      ))}
    </div>
  )
}


