import { useState, useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import './Chat.css'

interface Message {
  role: 'user' | 'assistant'
  content: string
}

interface Session {
  id: string
  title: string
  created_at: string
}

export default function Chat() {
  const [sessions, setSessions] = useState<Session[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    fetchSessions()
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    if (activeId) fetchMessages(activeId)
  }, [activeId])

  async function fetchSessions() {
    const res = await fetch('/sessions')
    const data = await res.json()
    setSessions(data)
  }

  async function fetchMessages(sessionId: string) {
    const res = await fetch(`/sessions/${sessionId}/messages`)
    const data = await res.json()
    setMessages(data)
  }

  async function startSession() {
    const res = await fetch('/sessions', { method: 'POST' })
    const session = await res.json()
    setSessions((prev) => [session, ...prev])
    setActiveId(session.id)
    setMessages([])
  }

  async function removeSession(id: string) {
    await fetch(`/sessions/${id}`, { method: 'DELETE' })
    setSessions((prev) => prev.filter((s) => s.id !== id))
    if (activeId === id) {
      setActiveId(null)
      setMessages([])
    }
  }

  async function send() {
    if (!input.trim() || !activeId || loading) return
    const userMsg: Message = { role: 'user', content: input.trim() }
    setMessages((prev) => [...prev, userMsg])
    setInput('')
    setLoading(true)

    try {
      const res = await fetch('/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: userMsg.content, session_id: activeId }),
      })

      if (!res.ok) {
        const data = await res.json()
        const msg = data?.detail ?? `Server error ${res.status}`
        setMessages((prev) => [...prev, { role: 'assistant', content: `Error: ${msg}` }])
        return
      }

      setLoading(false)
      setMessages((prev) => [...prev, { role: 'assistant', content: '' }])

      const reader = res.body!.getReader()
      const decoder = new TextDecoder()

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        const chunk = decoder.decode(value, { stream: true })
        for (const line of chunk.split('\n')) {
          if (!line.startsWith('data: ')) continue
          const token = line.slice(6)
          if (token === '[DONE]') break
          setMessages((prev) => {
            const updated = [...prev]
            updated[updated.length - 1] = {
              role: 'assistant',
              content: updated[updated.length - 1].content + token,
            }
            return updated
          })
        }
      }

      setSessions((prev) =>
        prev.map((s) =>
          s.id === activeId && s.title === 'New Chat'
            ? { ...s, title: userMsg.content.slice(0, 32) }
            : s
        )
      )
    } catch {
      setMessages((prev) => [...prev, { role: 'assistant', content: 'Error: could not reach the server.' }])
    } finally {
      setLoading(false)
    }
  }

  const activeSession = sessions.find((s) => s.id === activeId)

  return (
    <div className="chat-layout">
      <aside className="chat-sidebar">
        <button className="new-chat-btn" onClick={startSession}>+ New Chat</button>
        <ul className="session-list">
          {sessions.map((s) => (
            <li
              key={s.id}
              className={`session-item${s.id === activeId ? ' active' : ''}`}
              onClick={() => setActiveId(s.id)}
            >
              <span className="session-title">{s.title}</span>
              <button className="delete-btn" onClick={(e) => { e.stopPropagation(); removeSession(s.id) }}>×</button>
            </li>
          ))}
        </ul>
      </aside>

      <main className="chat-main">
        {!activeSession ? (
          <div className="chat-empty">
            <p>Start a new chat to begin.</p>
            <button className="new-chat-btn" onClick={startSession}>+ New Chat</button>
          </div>
        ) : (
          <>
            <div className="messages">
              {messages.length === 0 && (
                <div className="chat-empty"><p>Send a message to get started.</p></div>
              )}
              {messages.map((m, i) => (
                <div key={i} className={`message ${m.role}`}>
                  <div className="bubble">
                    {m.role === 'assistant'
                      ? <ReactMarkdown>{m.content}</ReactMarkdown>
                      : m.content}
                  </div>
                </div>
              ))}
              {loading && (
                <div className="message assistant">
                  <div className="bubble typing"><span /><span /><span /></div>
                </div>
              )}
              <div ref={bottomRef} />
            </div>

            <form className="input-row" onSubmit={(e) => { e.preventDefault(); send() }}>
              <textarea
                className="chat-input"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }}
                placeholder="Message… (Enter to send, Shift+Enter for newline)"
                rows={1}
              />
              <button className="send-btn" type="submit" disabled={loading || !input.trim()}>
                Send
              </button>
            </form>
          </>
        )}
      </main>
    </div>
  )
}
