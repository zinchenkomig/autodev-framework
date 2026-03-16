'use client'

import { useState } from 'react'
import { type Task, type Priority } from '@/lib/api'
import { X } from 'lucide-react'

interface AddTaskModalProps {
  onClose: () => void
  onAdd: (task: Task) => void
}

export function AddTaskModal({ onClose, onAdd }: AddTaskModalProps) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [repo, setRepo] = useState('backend')
  const [priority, setPriority] = useState<Priority>('normal')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!title.trim()) return

    const newTask: Task = {
      id: crypto.randomUUID(),
      title: title.trim(),
      description: description.trim(),
      source: 'manual',
      priority,
      status: 'queued',
      assigned_to: null,
      repo,
      issue_number: null,
      pr_number: null,
      created_by: 'user',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }

    onAdd(newTask)
    onClose()
  }

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/70 z-50" onClick={onClose} />

      {/* Modal */}
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div className="bg-[#09090B] border border-[#1F1F23] w-full max-w-md">
          {/* Header */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-[#1F1F23]">
            <span className="text-sm text-[#FAFAFA]">Add Task</span>
            <button
              onClick={onClose}
              className="text-[#3F3F46] hover:text-[#71717A] transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit} className="p-5 space-y-4">
            <div>
              <label className="block text-xs text-[#71717A] mb-1.5">Title</label>
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Task title..."
                required
                className="w-full bg-transparent border border-[#1F1F23] px-3 py-2 text-sm text-[#FAFAFA] placeholder-[#3F3F46] focus:outline-none focus:border-[#6366F1]/50 transition-colors"
              />
            </div>

            <div>
              <label className="block text-xs text-[#71717A] mb-1.5">Description</label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Describe the task..."
                rows={3}
                className="w-full bg-transparent border border-[#1F1F23] px-3 py-2 text-sm text-[#FAFAFA] placeholder-[#3F3F46] focus:outline-none focus:border-[#6366F1]/50 transition-colors resize-none"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-[#71717A] mb-1.5">Repository</label>
                <select
                  value={repo}
                  onChange={(e) => setRepo(e.target.value)}
                  className="w-full bg-[#09090B] border border-[#1F1F23] px-3 py-2 text-sm text-[#FAFAFA] focus:outline-none focus:border-[#6366F1]/50 transition-colors"
                >
                  <option value="backend">backend</option>
                  <option value="frontend">frontend</option>
                  <option value="infra">infra</option>
                </select>
              </div>
              <div>
                <label className="block text-xs text-[#71717A] mb-1.5">Priority</label>
                <select
                  value={priority}
                  onChange={(e) => setPriority(e.target.value as Priority)}
                  className="w-full bg-[#09090B] border border-[#1F1F23] px-3 py-2 text-sm text-[#FAFAFA] focus:outline-none focus:border-[#6366F1]/50 transition-colors"
                >
                  <option value="low">Low</option>
                  <option value="normal">Normal</option>
                  <option value="high">High</option>
                  <option value="critical">Critical</option>
                </select>
              </div>
            </div>

            <div className="flex gap-3 pt-2">
              <button
                type="button"
                onClick={onClose}
                className="flex-1 px-4 py-2 text-xs text-[#71717A] border border-[#1F1F23] hover:text-[#FAFAFA] hover:border-[#3F3F46] transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={!title.trim()}
                className="flex-1 px-4 py-2 text-xs text-[#FAFAFA] bg-[#6366F1] hover:bg-[#4F46E5] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                Add Task
              </button>
            </div>
          </form>
        </div>
      </div>
    </>
  )
}
