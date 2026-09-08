import type { PluginChartSeries, PluginWidget } from '../types'

const colors = ['#4285f4', '#7c5ce5', '#16a477', '#e48a26', '#dc4f64', '#22a3b6']

function chartBounds(series: PluginChartSeries[]) {
  const values = series.flatMap((item) => item.values).filter(Number.isFinite)
  const minimum = Math.min(0, ...values)
  const maximum = Math.max(1, ...values)
  return { minimum, maximum, range: maximum - minimum || 1 }
}

function LineChart({ widget }: { widget: Extract<PluginWidget, { kind: 'chart' }> }) {
  const width = 800
  const height = 280
  const padding = 32
  const bounds = chartBounds(widget.series)
  const x = (index: number) => padding + index * ((width - padding * 2) / Math.max(1, widget.labels.length - 1))
  const y = (value: number) => height - padding - ((value - bounds.minimum) / bounds.range) * (height - padding * 2)
  return <svg className="plugin-line-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={widget.title || 'График'}>
    {[0, 1, 2, 3, 4].map((line) => <line key={line} x1={padding} x2={width - padding} y1={padding + line * ((height - padding * 2) / 4)} y2={padding + line * ((height - padding * 2) / 4)} />)}
    {widget.series.map((series, seriesIndex) => {
      const points = series.values.map((value, index) => `${x(index)},${y(value)}`).join(' ')
      const color = series.color || colors[seriesIndex % colors.length]
      return <g key={`${series.name}-${seriesIndex}`}>
        {widget.chart_type === 'area' && <polygon points={`${padding},${height - padding} ${points} ${width - padding},${height - padding}`} fill={color} opacity=".13" />}
        <polyline points={points} fill="none" stroke={color} strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
        {series.values.map((value, index) => <circle key={index} cx={x(index)} cy={y(value)} r="4" fill={color}><title>{widget.labels[index]}: {value}</title></circle>)}
      </g>
    })}
  </svg>
}

function BarChart({ widget }: { widget: Extract<PluginWidget, { kind: 'chart' }> }) {
  const bounds = chartBounds(widget.series)
  return <div className="plugin-bar-chart" role="img" aria-label={widget.title || 'Столбчатый график'}>{widget.labels.map((label, labelIndex) => <div className="plugin-bar-group" key={`${label}-${labelIndex}`}><div className="plugin-bars">{widget.series.map((series, seriesIndex) => <span key={series.name} style={{ height: `${Math.max(2, ((series.values[labelIndex] - bounds.minimum) / bounds.range) * 100)}%`, background: series.color || colors[seriesIndex % colors.length] }} title={`${series.name}: ${series.values[labelIndex]}`} />)}</div><small>{label}</small></div>)}</div>
}

function PieChart({ widget }: { widget: Extract<PluginWidget, { kind: 'chart' }> }) {
  const values = widget.series[0]?.values.map((value) => Math.max(0, value)) ?? []
  const total = values.reduce((sum, value) => sum + value, 0) || 1
  let cursor = 0
  const stops = values.map((value, index) => {
    const start = cursor
    cursor += value / total * 100
    return `${widget.series[0]?.color || colors[index % colors.length]} ${start}% ${cursor}%`
  }).join(', ')
  return <div className="plugin-pie-layout"><div className={`plugin-pie ${widget.chart_type}`} style={{ background: `conic-gradient(${stops})` }} role="img" aria-label={widget.title || 'Круговая диаграмма'} /> <div className="plugin-chart-legend">{widget.labels.map((label, index) => <span key={label}><i style={{ background: widget.series[0]?.color || colors[index % colors.length] }} />{label}<strong>{values[index] ?? 0}</strong></span>)}</div></div>
}

function Chart({ widget }: { widget: Extract<PluginWidget, { kind: 'chart' }> }) {
  return <article className="plugin-widget plugin-chart-widget"><h3>{widget.title || 'График'}</h3>{widget.chart_type === 'bar' ? <BarChart widget={widget} /> : widget.chart_type === 'pie' || widget.chart_type === 'doughnut' ? <PieChart widget={widget} /> : <LineChart widget={widget} />}<div className="plugin-series-legend">{widget.series.map((series, index) => <span key={series.name}><i style={{ background: series.color || colors[index % colors.length] }} />{series.name}</span>)}</div></article>
}

export function PluginWidgets({ widgets }: { widgets: PluginWidget[] }) {
  if (!widgets.length) return null
  return <section className="plugin-widgets" aria-label="Динамические данные плагина">{widgets.map((widget) => {
    if (widget.kind === 'text') return <article className={`plugin-widget plugin-text tone-${widget.tone ?? 'default'}`} key={widget.id}>{widget.title && <h3>{widget.title}</h3>}<p>{widget.text}</p></article>
    if (widget.kind === 'metric') return <article className={`plugin-widget plugin-metric tone-${widget.tone ?? 'default'}`} key={widget.id}><span>{widget.label}</span><strong>{String(widget.value ?? '—')}</strong>{widget.detail && <small>{widget.detail}</small>}</article>
    if (widget.kind === 'image') return <figure className="plugin-widget plugin-image" key={widget.id}>{widget.title && <h3>{widget.title}</h3>}<img src={widget.src} alt={widget.alt} />{widget.caption && <figcaption>{widget.caption}</figcaption>}</figure>
    if (widget.kind === 'chart') return <Chart widget={widget} key={widget.id} />
    return <article className="plugin-widget plugin-table-widget" key={widget.id}>{widget.title && <h3>{widget.title}</h3>}<div className="plugin-table-scroll"><table><thead><tr>{widget.columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{widget.rows.map((row, index) => <tr key={index}>{row.map((value, cell) => <td key={cell}>{typeof value === 'object' ? JSON.stringify(value) : String(value ?? '')}</td>)}</tr>)}</tbody></table></div></article>
  })}</section>
}
