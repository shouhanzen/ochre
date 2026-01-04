type Item = 'explorer' | 'sessions' | 'pending' | 'settings' | 'chat'

export function ActivityBar(props: {
  active: Item
  onSelect: (item: Item) => void
}) {
  const items: { id: Item; label: string; icon: string }[] = [
    { id: 'explorer', label: 'Explorer', icon: '❐' },
    { id: 'sessions', label: 'Sessions', icon: '⎘' },
    { id: 'pending', label: 'Pending', icon: '◎' },
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


