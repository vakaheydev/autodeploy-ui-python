import { useEffect, useState } from 'react'

export type Theme = 'light' | 'dark'

function initialTheme(): Theme {
  const saved = window.localStorage.getItem('autodeploy.theme')
  if (saved === 'light' || saved === 'dark') return saved
  const preloaded = document.documentElement.dataset.theme
  return preloaded === 'light' || preloaded === 'dark' ? preloaded : 'dark'
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(initialTheme)

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    document.documentElement.style.colorScheme = theme
    document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')
      ?.setAttribute('content', theme === 'dark' ? '#0b1220' : '#f4f7fb')
    window.localStorage.setItem('autodeploy.theme', theme)
  }, [theme])

  return {
    theme,
    toggleTheme: () => setTheme((current) => current === 'light' ? 'dark' : 'light'),
  }
}
