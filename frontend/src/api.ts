export type FileKind = 'file' | 'dir'

export type FileEntry = {
  name: string
  path: string
  kind: FileKind
  size: number | null
}

export type Task = {
  id: string
  text: string
  done: boolean
  created_at: string
  updated_at: string
}

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `HTTP ${res.status}`)
  }
  return (await res.json()) as T
}

export async function fsList(path: string): Promise<{ entries: FileEntry[] }> {
  return await jsonFetch(`/api/fs/list?path=${encodeURIComponent(path)}`)
}

export async function fsRead(path: string): Promise<{ content: string }> {
  return await jsonFetch(`/api/fs/read?path=${encodeURIComponent(path)}`)
}

export async function fsWrite(path: string, content: string): Promise<void> {
  await jsonFetch(`/api/fs/write`, {
    method: 'PUT',
    body: JSON.stringify({ path, content }),
  })
}

export async function getTodayTodos(): Promise<{ day: string; tasks: Task[] }> {
  return await jsonFetch(`/api/todos/today`)
}

export async function addTodayTodo(text: string): Promise<{ day: string; tasks: Task[] }> {
  return await jsonFetch(`/api/todos/today/add`, {
    method: 'POST',
    body: JSON.stringify({ text }),
  })
}

export async function setTodayTodoDone(id: string, done: boolean): Promise<{ day: string; tasks: Task[] }> {
  return await jsonFetch(`/api/todos/today/set_done`, {
    method: 'PATCH',
    body: JSON.stringify({ id, done }),
  })
}



