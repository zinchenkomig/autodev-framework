'use client'

import { ArrowLeft } from 'lucide-react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { EMPTY_PROJECT, ProjectForm } from '@/components/ProjectForm'
import { api } from '@/lib/api'

export default function NewProjectPage() {
  const router = useRouter()
  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <Link href="/projects" className="inline-flex items-center gap-1 text-sm text-muted hover:text-fg">
        <ArrowLeft size={16} /> Проекты
      </Link>
      <h1 className="text-xl font-semibold">Новый проект</h1>
      <ProjectForm
        initial={EMPTY_PROJECT}
        isNew
        onSubmit={async (p, newRepo) => {
          await api.createProject(p, newRepo)
          router.push(`/projects/${p.id}`)
        }}
      />
    </div>
  )
}
