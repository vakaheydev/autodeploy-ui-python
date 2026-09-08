(() => {
  let theme = 'dark'
  try {
    const saved = window.localStorage.getItem('autodeploy.theme')
    if (saved === 'light' || saved === 'dark') theme = saved
  } catch {
    // Storage can be disabled by browser policy; dark remains the safe default.
  }
  document.documentElement.dataset.theme = theme
  document.documentElement.style.colorScheme = theme
  const meta = document.querySelector('meta[name="theme-color"]')
  if (meta) meta.setAttribute('content', theme === 'dark' ? '#0b1220' : '#f4f7fb')
})()
