import { NextRequest, NextResponse } from 'next/server'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://autodev-api:8000'

export async function POST(req: NextRequest) {
  try {
    const body = await req.json()
    
    // Forward to backend PM agent
    const res = await fetch(`${API_URL}/api/pm/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    
    if (!res.ok) {
      throw new Error(`Backend error: ${res.status}`)
    }
    
    const data = await res.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error('PM chat error:', error)
    return NextResponse.json(
      { response: 'Ошибка связи с PM агентом. Попробуй позже.' },
      { status: 500 }
    )
  }
}
