import { useEffect, useState, type FormEvent, type KeyboardEvent } from 'react'
import RouteMap, { type AnalysisResult, type CorridorForecast, type RouteResult } from './RouteMap'
import { requestCurrentLocation, reverseGeocode, type ApproximateLocation } from './geolocation'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api'
const HAS_MAP_DISPLAY_TOKEN = Boolean(import.meta.env.VITE_MAPBOX_ACCESS_TOKEN)

type AnalysisRequest = {
  origin: string
  destination: string
  departure_time: string
  load_weight_lb: number
  checkpoint_interval_miles: number
}

type LocationSuggestion = {
  id: string
  label: string
}

type LocationSuggestionResponse = {
  message?: string
  suggestions?: LocationSuggestion[]
}

type LocationAutocompleteProps = {
  id: string
  value: string
  onChange: (value: string) => void
  placeholder: string
  pinClassName: string
  onUseCurrentLocation?: () => Promise<string | null>
  locationLoading?: boolean
}

function LocationAutocomplete({ id, value, onChange, placeholder, pinClassName, onUseCurrentLocation, locationLoading }: LocationAutocompleteProps) {
  const [suggestions, setSuggestions] = useState<LocationSuggestion[]>([])
  const [isOpen, setIsOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(-1)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selectedValue, setSelectedValue] = useState('')
  const suggestionListId = `${id}-suggestions`

  useEffect(() => {
    const query = value.trim()
    if ((selectedValue && selectedValue === query) || query.length < 3) {
      setSuggestions([])
      setIsOpen(false)
      setLoading(false)
      setError('')
      return
    }

    const controller = new AbortController()
    const timeout = window.setTimeout(async () => {
      setLoading(true)
      setError('')
      try {
        const response = await fetch(
          `${API_BASE}/location-suggestions/?q=${encodeURIComponent(query)}`,
          { signal: controller.signal },
        )
        const contentType = response.headers.get('content-type') ?? ''
        const body: LocationSuggestionResponse | null = contentType.includes('application/json')
          ? await response.json()
          : null
        if (!response.ok) {
          throw new Error(body?.message ?? 'Location suggestions are unavailable right now.')
        }
        setSuggestions(body?.suggestions ?? [])
        setActiveIndex(-1)
        setIsOpen(true)
      } catch (suggestionError) {
        if (suggestionError instanceof DOMException && suggestionError.name === 'AbortError') return
        setSuggestions([])
        setIsOpen(false)
        setError(suggestionError instanceof Error ? suggestionError.message : 'Location suggestions are unavailable right now.')
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }, 300)

    return () => {
      window.clearTimeout(timeout)
      controller.abort()
    }
  }, [value, selectedValue])

  function chooseSuggestion(suggestion: LocationSuggestion) {
    setSelectedValue(suggestion.label.trim())
    onChange(suggestion.label)
    setSuggestions([])
    setIsOpen(false)
    setActiveIndex(-1)
    setError('')
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown' && suggestions.length > 0) {
      event.preventDefault()
      setIsOpen(true)
      setActiveIndex((current) => current < suggestions.length - 1 ? current + 1 : 0)
    } else if (event.key === 'ArrowUp' && suggestions.length > 0) {
      event.preventDefault()
      setIsOpen(true)
      setActiveIndex((current) => current <= 0 ? suggestions.length - 1 : current - 1)
    } else if (event.key === 'Enter' && isOpen && activeIndex >= 0) {
      event.preventDefault()
      chooseSuggestion(suggestions[activeIndex])
    } else if (event.key === 'Escape') {
      setIsOpen(false)
      setActiveIndex(-1)
    }
  }

  async function handleUseCurrentLocation() {
    if (!onUseCurrentLocation) return
    const label = await onUseCurrentLocation()
    if (!label) return
    setSelectedValue(label.trim())
    setSuggestions([])
    setIsOpen(false)
    setActiveIndex(-1)
    setError('')
  }

  return (
    <div className="location-autocomplete">
      <div className="input-wrap">
        <span className={`pin ${pinClassName}`} aria-hidden="true" />
        <input
          id={id}
          value={value}
          onChange={(event) => {
            setSelectedValue('')
            setError('')
            onChange(event.target.value)
          }}
          onFocus={() => { if (suggestions.length > 0) setIsOpen(true) }}
          onBlur={() => window.setTimeout(() => setIsOpen(false), 150)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={isOpen && suggestions.length > 0}
          aria-controls={suggestionListId}
          aria-activedescendant={activeIndex >= 0 ? `${suggestionListId}-${activeIndex}` : undefined}
          autoComplete="off"
          required
        />
        {onUseCurrentLocation && (
          <button
            className="location-action"
            type="button"
            onClick={handleUseCurrentLocation}
            disabled={locationLoading}
            aria-label="Use my current location as the trip origin"
          >
            {locationLoading ? 'Locating…' : 'Use my location'}
          </button>
        )}
      </div>
      {isOpen && suggestions.length > 0 && (
        <ul className="suggestion-list" id={suggestionListId} role="listbox">
          {suggestions.map((suggestion, index) => (
            <li
              className={`suggestion-option${index === activeIndex ? ' suggestion-option-active' : ''}`}
              id={`${suggestionListId}-${index}`}
              key={suggestion.id}
              role="option"
              aria-selected={index === activeIndex}
              onMouseEnter={() => setActiveIndex(index)}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => chooseSuggestion(suggestion)}
            >
              {suggestion.label}
            </li>
          ))}
        </ul>
      )}
      {(loading || error) && (
        <div className="suggestion-status" role="status">
          {loading ? 'Searching locations…' : error}
        </div>
      )}
    </div>
  )
}

export default function App() {
  const [origin, setOrigin] = useState('')
  const [destination, setDestination] = useState('')
  const [departureTime, setDepartureTime] = useState('')
  const [loadWeight, setLoadWeight] = useState('')
  const [interval, setInterval] = useState(25)
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(false)
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null)
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null)
  const [forecastHour, setForecastHour] = useState(0)
  const [appliedForecastHour, setAppliedForecastHour] = useState(0)
  const [corridorForecast, setCorridorForecast] = useState<CorridorForecast | null>(null)
  const [forecastLoading, setForecastLoading] = useState(false)
  const [forecastError, setForecastError] = useState('')
  const [locationLoading, setLocationLoading] = useState(false)
  const [locationMessage, setLocationMessage] = useState('')
  const [focusLocation, setFocusLocation] = useState<ApproximateLocation | null>(null)

  async function useCurrentLocationAsOrigin(): Promise<string | null> {
    setLocationLoading(true)
    setLocationMessage('')
    try {
      const location = await requestCurrentLocation(2)
      const resolved = await reverseGeocode(location, 'place,locality,region,country')
      if (!resolved?.label) {
        throw new Error('Could not identify your location. You can still search for any origin.')
      }
      setOrigin(resolved.label)
      setFocusLocation(location)
      return resolved.label
    } catch (error) {
      setLocationMessage(error instanceof Error ? error.message : 'Could not determine your location. You can still search for any origin.')
      return null
    } finally {
      setLocationLoading(false)
    }
  }

  async function submitTrip(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setMessage('')
    if (!HAS_MAP_DISPLAY_TOKEN) {
      setMessage('Trip planning is unavailable right now. Please try again later.')
      return
    }
    setLoading(true)
    const payload: AnalysisRequest = {
      origin: origin.trim(),
      destination: destination.trim(),
      departure_time: new Date(departureTime).toISOString(),
      load_weight_lb: Number(loadWeight),
      checkpoint_interval_miles: interval,
    }
    try {
      const response = await fetch(`${API_BASE}/route-analysis/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      const body = await response.json()
      if (!response.ok) throw new Error(body.message ?? 'Route analysis could not be started.')
      const result = body as AnalysisResult
      setAnalysis(result)
      setSelectedRouteId(result.recommendation_id ?? result.routes[0]?.id ?? null)
      setForecastHour(0)
      setAppliedForecastHour(0)
      setCorridorForecast(null)
      setForecastError('')
      setMessage(result.warnings.join(' '))
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not connect to the routing service.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!analysis) return
    const controller = new AbortController()
    const timeout = window.setTimeout(async () => {
      setForecastLoading(true)
      setForecastError('')
      const checkpoints = analysis.routes.flatMap((route) => route.checkpoints.map((point) => ({
        route_id: route.id,
        mile: point.mile,
        longitude: point.longitude,
        latitude: point.latitude,
      })))
      try {
        const response = await fetch(`${API_BASE}/corridor-forecast/`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          signal: controller.signal,
          body: JSON.stringify({
            departure_time: analysis.departure_time,
            load_weight_lb: analysis.load_weight_lb,
            forecast_offset_hours: appliedForecastHour,
            checkpoints,
          }),
        })
        const body = await response.json()
        if (!response.ok) throw new Error(body.message ?? 'Corridor forecast is unavailable.')
        setCorridorForecast(body as CorridorForecast)
      } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') return
        setForecastError(error instanceof Error ? error.message : 'Corridor forecast is unavailable.')
      } finally {
        if (!controller.signal.aborted) setForecastLoading(false)
      }
    }, 350)
    return () => {
      window.clearTimeout(timeout)
      controller.abort()
    }
  }, [analysis, appliedForecastHour])

  const selectedRoute: RouteResult | undefined = analysis?.routes.find((route) => route.id === selectedRouteId)

  function durationLabel(seconds: number) {
    const hours = Math.floor(seconds / 3600)
    const minutes = Math.round((seconds % 3600) / 60)
    return hours ? `${hours}h ${minutes}m` : `${minutes}m`
  }

  function localTime(value: string) {
    return new Intl.DateTimeFormat(undefined, { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).format(new Date(value))
  }

  function recommendationReason(result: AnalysisResult) {
    const recommended = result.routes.find((route) => route.id === result.recommendation_id)
    if (!result.routes.length) return 'No route options were available for this trip.'
    if (!recommended) return 'None of the available routes meets the weather safety thresholds.'

    const recommendedRisk = recommended.risk_summary
    const risksAreComparable = result.routes.every((route) =>
      route.risk_summary.severe_miles === recommendedRisk.severe_miles &&
      route.risk_summary.high_miles === recommendedRisk.high_miles &&
      route.risk_summary.average_risk === recommendedRisk.average_risk,
    )
    return risksAreComparable
      ? 'Weather risk is similar across the options; this route is recommended for its shorter travel time.'
      : 'Recommendation prioritizes fewer severe miles, fewer high-risk miles, lower average risk, then travel time.'
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#top" aria-label="Weather-Aware Routing home">
          <span className="brand-mark" aria-hidden="true">↗</span>
          <span>ROUTEWISE<span className="brand-subtitle">WEATHER INTELLIGENCE</span></span>
        </a>

        <div className="sidebar-label">WORKSPACE</div>
        <button className="nav-item nav-item-active" type="button"><span>⌁</span> Route planner</button>
        <div className="sidebar-note">
          <div className="note-icon">i</div>
          <div><strong>Plan with context</strong><p>Compare weather exposure and travel time before you depart.</p></div>
        </div>
        <div className="sidebar-footer">
          <span className={`status-dot${analysis ? ' status-dot-connected' : ''}`} />
          WEATHER DATA CONNECTION
          <span className={`status-label${analysis ? ' status-label-connected' : ''}`}>
            {analysis ? 'CONNECTED' : 'AWAITING ANALYSIS'}
          </span>
        </div>
      </aside>

      <section className="workspace" id="top">
        <header className="topbar">
          <div><div className="eyebrow">ROUTE PLANNING</div><h1>Weather-aware routing</h1></div>
          <div className="topbar-meta"><span className="live-dot" /> Forecast horizon <strong>48 hours</strong></div>
        </header>

        <div className="content-grid">
          <section className="trip-panel" aria-labelledby="trip-heading">
            <div className="panel-heading"><div><div className="eyebrow">NEW ANALYSIS</div><h2 id="trip-heading">Plan a trip</h2></div><span className="step-badge">01</span></div>
            <p className="panel-intro">Compare routes worldwide using weather at your estimated arrival times.</p>

            <form onSubmit={submitTrip}>
              <label className="field-label" htmlFor="origin">ORIGIN</label>
              <LocationAutocomplete
                id="origin"
                value={origin}
                onChange={(value) => { setOrigin(value); setLocationMessage('') }}
                placeholder="City, address, or ZIP code"
                pinClassName="pin-origin"
                onUseCurrentLocation={useCurrentLocationAsOrigin}
                locationLoading={locationLoading}
              />
              {locationMessage && <p className="location-message" role="status">{locationMessage}</p>}

              <div className="route-connector" aria-hidden="true"><span /></div>

              <label className="field-label" htmlFor="destination">DESTINATION</label>
              <LocationAutocomplete id="destination" value={destination} onChange={setDestination} placeholder="City, address, or ZIP code" pinClassName="pin-destination" />

              <div className="field-row">
                <div className="field-group"><label className="field-label" htmlFor="departure">DEPARTURE</label><input id="departure" className="text-input" type="datetime-local" value={departureTime} onChange={(event) => setDepartureTime(event.target.value)} required /></div>
                <div className="field-group"><label className="field-label" htmlFor="load">LOAD WEIGHT <span>(lb)</span></label><input id="load" className="text-input" type="number" min="0" step="1" value={loadWeight} onChange={(event) => setLoadWeight(event.target.value)} placeholder="e.g. 32,000" required /></div>
              </div>

              <fieldset className="interval-fieldset"><legend className="field-label">WEATHER CHECKPOINTS</legend><div className="interval-options">{[10, 25, 50].map((miles) => <button key={miles} type="button" className={interval === miles ? 'interval-option selected' : 'interval-option'} onClick={() => setInterval(miles)} aria-pressed={interval === miles}>{miles} <small>mi</small></button>)}</div><p className="field-hint">Forecasts sampled along each route.</p></fieldset>

              <button className="submit-button" type="submit" disabled={loading}>{loading ? 'Preparing analysis…' : 'Compare routes'}<span aria-hidden="true">→</span></button>
              {message && <p className="form-message" role="status">{message}</p>}
            </form>
          </section>

          <section className="map-panel" aria-label="Route map and analysis results">
            <div className="map-toolbar"><div><div className="eyebrow">TRIP OVERVIEW</div><h2>Route conditions</h2></div><span className="map-state">{analysis ? `${analysis.route_count} OF 3 ROUTES` : 'AWAITING TRIP DETAILS'}</span></div>
            <div className="map-stage"><RouteMap analysis={analysis} selectedRouteId={selectedRouteId} corridorForecast={corridorForecast} focusLocation={focusLocation} /><div className="map-legend"><span><i className="legend-line legend-primary" /> Recommended route</span><span><i className="legend-line legend-alt" /> Other options</span><span><i className="legend-dot" /> Forecast risk</span></div></div>
            <div className="forecast-bar">
              <div><span className="forecast-glyph">◷</span><div><strong>Forecast timeline</strong><small>{analysis ? corridorForecast ? `Map colors: ${localTime(corridorForecast.forecast_time)} · table: checkpoint ETAs` : 'Loading corridor forecast…' : 'Choose a point in the next 48 hours'}</small></div></div>
              <div className="forecast-slider-control">
                <label className="forecast-slider-label">
                  <span>0 h</span>
                  <input type="range" min="0" max="48" step="1" value={forecastHour} disabled={!analysis || forecastLoading} onChange={(event) => setForecastHour(Number(event.target.value))} onPointerUp={() => setAppliedForecastHour(forecastHour)} onKeyUp={() => setAppliedForecastHour(forecastHour)} onTouchEnd={() => setAppliedForecastHour(forecastHour)} aria-label="Forecast hours after departure" />
                  <span>48 h</span>
                </label>
                <span className="forecast-slider-selected" aria-live="polite">Selected: {forecastHour} h after departure</span>
              </div>
            </div>
            {forecastError && <div className="forecast-error" role="status">Forecast heatmap unavailable: {forecastError}</div>}
            {analysis ? (
              <div className="analysis-content">
                <div className="analysis-context"><span>{analysis.origin.label}</span><i aria-hidden="true">→</i><span>{analysis.destination.label}</span><small>Departing {localTime(analysis.departure_time)}</small></div>
                <div className="route-list" aria-label="Route options">{analysis.routes.map((route) => <button key={route.id} type="button" className={`route-card ${selectedRouteId === route.id ? 'route-card-selected' : ''}`} onClick={() => setSelectedRouteId(route.id)} aria-pressed={selectedRouteId === route.id}>
                  <span className={`rank-number ${route.id === analysis.recommendation_id ? 'rank-recommended' : ''}`}>{route.rank.toString().padStart(2, '0')}</span>
                  <span className="route-main"><strong>{route.id === analysis.recommendation_id ? 'Recommended route' : `Route option ${route.rank}`}</strong><small>{route.strategy.replaceAll('-', ' ')} · {route.distance_miles.toLocaleString()} mi</small></span>
                  <span className="route-stats"><strong>{durationLabel(route.duration_seconds)}</strong><small>{route.risk_summary.severe_miles} severe mi · {route.risk_summary.high_miles} high mi</small></span>
                  <span className={`risk-pill risk-${!route.risk_summary.eligible ? 'stop' : route.risk_summary.average_risk >= 2 ? 'high' : route.risk_summary.average_risk >= 1 ? 'moderate' : 'low'}`}>{route.risk_summary.eligible ? `Avg ${route.risk_summary.average_risk}/4` : 'No Travel'}</span>
                </button>)}</div>
                <p className="recommendation-reason" role="status">{recommendationReason(analysis)}</p>
                {selectedRoute && <div className="checkpoint-section"><div className="checkpoint-heading"><div><div className="eyebrow">SELECTED ROUTE</div><strong>Weather checkpoints</strong></div><span>{selectedRoute.checkpoints.length} samples · every {analysis.checkpoint_interval_miles} mi</span></div><div className="checkpoint-scroll"><table><thead><tr><th>Route mile</th><th>Arrival</th><th>Risk</th><th>Wind</th><th>Rain</th><th>Snow</th></tr></thead><tbody>{selectedRoute.checkpoints.map((point) => <tr key={`${selectedRoute.id}-${point.mile}`}><td>{point.mile.toLocaleString()} mi</td><td>{localTime(point.arrival_time)}</td><td><span className={`risk-text risk-text-${point.risk.toLowerCase().replace(' ', '-')}`}>{point.risk}</span></td><td>{point.weather.wind_mph} mph</td><td>{point.weather.rain_in_per_hour} in/hr</td><td>{point.weather.snow_in_per_hour} in/hr</td></tr>)}</tbody></table></div><p className="eta-note">Route ETA: {localTime(selectedRoute.estimated_arrival)} · Average risk score: {selectedRoute.risk_summary.average_risk}/4</p></div>}
              </div>
            ) : <div className="route-summary-placeholder"><span className="summary-dash" /><span>Three route options, checkpoint risks, ETAs, and summaries will appear after analysis.</span></div>}
          </section>
        </div>
        <footer className="page-footer"><span>Weather-aware routing</span><span>{analysis ? <>Weather data by <a href="https://open-meteo.com/" target="_blank" rel="noreferrer">{analysis.weather_source}</a> (units converted and risk classified) · Routes: {analysis.routing_source}</> : 'Forecasts are estimates and may change as conditions update.'}</span></footer>
      </section>
    </main>
  )
}
